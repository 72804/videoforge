from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from docprod.product.auth import TelegramInitData, validate_init_data
from docprod.product.contracts import JobStatusView, ProjectSummary, SceneSummary
from docprod.product.enums import (
    AspectRatio,
    AssetKind,
    AttemptStatus,
    DurationMode,
    JobStatus,
    LedgerStatus,
    PaymentStatus,
    PlanItemType,
    ProjectStatus,
    ProviderBilledStatus,
    ProviderOutcome,
    QuoteStatus,
    ReferenceMode,
    StarTxnType,
)
from docprod.product.errors import (
    AuthorizationError,
    JobConflictError,
    LimitExceededError,
    NotFoundError,
    OwnershipError,
    ProductError,
    QuoteError,
    SceneLockedError,
)
from docprod.product.ids import new_id
from docprod.product.invalidation import InvalidationEvent, effects_for
from docprod.product.jobs import transition
from docprod.product.limits import DEFAULT_LIMITS, ProductLimits
from docprod.product.models import (
    Asset,
    AssetVersion,
    Character,
    CharacterReference,
    GenerationAttempt,
    GenerationJob,
    GenerationPlan,
    NotificationOutbox,
    Project,
    Render,
    Scene,
    SceneVersion,
    StarQuote,
    StarTransaction,
    TelegramPayment,
    TelegramUser,
    utcnow,
)
from docprod.product.moderation import ModerationHooks
from docprod.product.plans import (
    PricingPolicy,
    assemble_plan,
    default_plan_items,
    hash_quote,
)
from docprod.product.repository import MemoryRepository
from docprod.product.settlement import classify_attempt
from docprod.product.storage import MemoryStorageBackend, StorageBackend

Clock = Callable[[], datetime]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ProductService:
    def __init__(
        self,
        repo: MemoryRepository | None = None,
        *,
        storage: StorageBackend | None = None,
        limits: ProductLimits | None = None,
        pricing: PricingPolicy | None = None,
        moderation: ModerationHooks | None = None,
        bot_token: str = "test-bot-token",
        clock: Clock | None = None,
    ) -> None:
        self.repo = repo or MemoryRepository()
        self.storage = storage or MemoryStorageBackend()
        self.limits = limits or DEFAULT_LIMITS
        self.pricing = pricing or PricingPolicy()
        self.moderation = moderation or ModerationHooks()
        self.bot_token = bot_token
        self.clock = clock or utcnow

    def authenticate_telegram(self, init_data: str) -> TelegramUser:
        parsed: TelegramInitData = validate_init_data(
            init_data,
            bot_token=self.bot_token,
            now=self.clock(),
            limits=self.limits,
        )
        user = TelegramUser(
            telegram_user_id=parsed.user.id,
            username=parsed.user.username,
            first_name=parsed.user.first_name,
            language_code=parsed.user.language_code,
            created_at=self.clock(),
            updated_at=self.clock(),
        )
        return self.repo.put_user(user)

    def _require_project(self, user_id: str, project_id: str) -> Project:
        project = self.repo.projects.get(project_id)
        if project is None:
            raise NotFoundError("project not found")
        if project.user_id != user_id:
            raise OwnershipError("project does not belong to user")
        return project

    def _require_character(self, user_id: str, character_id: str) -> Character:
        character = self.repo.characters.get(character_id)
        if character is None:
            raise NotFoundError("character not found")
        project = self._require_project(user_id, character.project_id)
        if character.project_id != project.id:
            raise OwnershipError("character does not belong to project")
        return character

    def _require_scene(self, user_id: str, scene_id: str) -> Scene:
        scene = self.repo.scenes.get(scene_id)
        if scene is None:
            raise NotFoundError("scene not found")
        self._require_project(user_id, scene.project_id)
        return scene

    def _supersede_quotes(self, project_id: str) -> None:
        for quote in self.repo.quotes.values():
            if quote.project_id == project_id and quote.status is QuoteStatus.OPEN:
                quote.status = QuoteStatus.SUPERSEDED

    def create_project(
        self,
        user_id: str,
        *,
        title: str,
        prompt: str,
        duration_mode: DurationMode = DurationMode.AUTO,
        target_duration_seconds: float | None = None,
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
        language: str = "en",
        quality_profile: str = "balanced",
        default_image_model: str = "auto",
        default_video_model: str = "auto",
        default_text_model: str = "auto",
        default_voice_model: str = "auto",
        style: str = "",
    ) -> Project:
        if len(self.repo.projects_for(user_id)) >= self.limits.max_projects_per_user:
            raise LimitExceededError("max projects exceeded")
        gate = self.moderation.check_prompt(prompt)
        if not gate.allowed:
            raise ProductError(gate.reason or "prompt rejected")
        if duration_mode is DurationMode.FIXED:
            if (
                target_duration_seconds is None
                or target_duration_seconds > self.limits.max_duration_seconds
            ):
                raise LimitExceededError("duration exceeds product limit")
        project = Project(
            user_id=user_id,
            title=title,
            prompt=prompt,
            duration_mode=duration_mode,
            target_duration_seconds=target_duration_seconds,
            aspect_ratio=aspect_ratio,
            language=language,
            quality_profile=quality_profile,
            default_image_model=default_image_model,
            default_video_model=default_video_model,
            default_text_model=default_text_model,
            default_voice_model=default_voice_model,
            style=style,
        )
        return self.repo.put_project(project)

    def update_project(self, user_id: str, project_id: str, **fields: object) -> Project:
        project = self._require_project(user_id, project_id)
        data = project.model_dump()
        data.update(fields)
        data["updated_at"] = self.clock()
        updated = Project.model_validate(data)
        self._supersede_quotes(project_id)
        return self.repo.put_project(updated)

    def archive_project(self, user_id: str, project_id: str) -> Project:
        project = self._require_project(user_id, project_id)
        project.status = ProjectStatus.ARCHIVED
        project.archived_at = self.clock()
        project.updated_at = self.clock()
        return project

    def update_character(self, user_id: str, character_id: str, **fields: object) -> Character:
        character = self._require_character(user_id, character_id)
        data = character.model_dump()
        data.update(fields)
        updated = Character.model_validate(data)
        self.repo.characters[updated.id] = updated
        return updated

    def delete_character(self, user_id: str, character_id: str) -> None:
        character = self._require_character(user_id, character_id)
        del self.repo.characters[character_id]
        for ref_id, ref in list(self.repo.references.items()):
            if ref.character_id == character_id:
                del self.repo.references[ref_id]
        self._invalidate_character(character.project_id, character_id)

    def ensure_mock_outline(self, user_id: str, project_id: str) -> None:
        if self.repo.scenes_for(project_id):
            return
        project = self._require_project(user_id, project_id)
        chars = [c.id for c in self.repo.characters_for(project_id)]
        beats = (
            f"{project.prompt} Opening beat in the apartment.",
            f"{project.prompt} They hesitate over the object.",
            f"{project.prompt} Evening light, unresolved.",
        )
        for index, visual in enumerate(beats, start=1):
            self.add_scene(
                user_id,
                project_id,
                visual_prompt=visual,
                motion_prompt="restrained natural motion",
                character_ids=chars[:2],
                duration_seconds=4.0 + index,
                narration=visual,
            )

    def add_character(
        self,
        user_id: str,
        project_id: str,
        *,
        name: str,
        description: str = "",
    ) -> Character:
        self._require_project(user_id, project_id)
        if len(self.repo.characters_for(project_id)) >= self.limits.max_characters_per_project:
            raise LimitExceededError("max characters exceeded")
        character = Character(project_id=project_id, name=name, description=description)
        self.repo.characters[character.id] = character
        return character

    def add_character_reference(
        self,
        user_id: str,
        character_id: str,
        image: bytes,
        *,
        mode: ReferenceMode = ReferenceMode.CUSTOM,
        primary: bool = True,
        role: str = "primary",
        width: int = 0,
        height: int = 0,
        mime: str = "",
    ) -> CharacterReference:
        character = self._require_character(user_id, character_id)
        if len(image) > self.limits.max_upload_bytes:
            raise LimitExceededError("upload too large")
        gate = self.moderation.check_image(image)
        if not gate.allowed:
            raise ProductError(gate.reason or "image rejected")
        key = f"projects/{character.project_id}/characters/{character.id}/{new_id()}.bin"
        self.storage.put_bytes(key, image, content_type="image/jpeg")
        ref = CharacterReference(
            character_id=character.id,
            project_id=character.project_id,
            storage_key=key,
            sha256=_sha256_bytes(image),
            mode=mode,
            primary=primary,
            role=role,
            width=width,
            height=height,
            mime=mime,
        )
        self.repo.references[ref.id] = ref
        if primary:
            character.primary_reference_id = ref.id
        self._invalidate_character(character.project_id, character.id)
        return ref

    def _invalidate_character(self, project_id: str, character_id: str) -> None:
        flags = effects_for(InvalidationEvent.CHARACTER_REFERENCE_CHANGED)
        for version in self.repo.active_versions(project_id):
            if character_id in version.character_ids:
                if flags["image"]:
                    version.image_stale = True
                if flags["video"]:
                    version.video_stale = True
        if flags["render"]:
            self._stale_renders(project_id)

    def _stale_renders(self, project_id: str) -> None:
        for render in self.repo.renders.values():
            if render.project_id == project_id:
                render.stale = True

    def add_scene(
        self,
        user_id: str,
        project_id: str,
        *,
        visual_prompt: str,
        motion_prompt: str = "",
        character_ids: list[str] | None = None,
        duration_seconds: float = 4.0,
        narration: str = "",
        dialogue: str = "",
        image_model: str = "auto",
        video_model: str = "auto",
    ) -> Scene:
        self._require_project(user_id, project_id)
        if len(self.repo.scenes_for(project_id)) >= self.limits.max_scenes_per_project:
            raise LimitExceededError("max scenes exceeded")
        order = len(self.repo.scenes_for(project_id))
        scene = Scene(project_id=project_id, order_index=order)
        version = SceneVersion(
            scene_id=scene.id,
            project_id=project_id,
            visual_prompt=visual_prompt,
            motion_prompt=motion_prompt,
            character_ids=list(character_ids or []),
            duration_seconds=duration_seconds,
            narration=narration,
            dialogue=dialogue,
            image_model=image_model,
            video_model=video_model,
        )
        scene.active_version_id = version.id
        self.repo.scenes[scene.id] = scene
        self.repo.scene_versions[version.id] = version
        self._stale_renders(project_id)
        return scene

    def _active_version(self, scene: Scene) -> SceneVersion:
        if not scene.active_version_id:
            raise ProductError("scene has no active version")
        return self.repo.scene_versions[scene.active_version_id]

    def _fork_version(self, scene: Scene, **updates: object) -> SceneVersion:
        current = self._active_version(scene)
        payload = current.model_dump()
        payload.update(updates)
        payload["id"] = new_id()
        payload["created_at"] = self.clock()
        version = SceneVersion.model_validate(payload)
        self.repo.scene_versions[version.id] = version
        scene.active_version_id = version.id
        return version

    def edit_scene(self, user_id: str, scene_id: str, **fields: object) -> SceneVersion:
        scene = self._require_scene(user_id, scene_id)
        if scene.locked:
            raise SceneLockedError("unlock the scene before editing")
        current = self._active_version(scene)
        event = None
        if "visual_prompt" in fields:
            event = InvalidationEvent.SCENE_VISUAL_PROMPT_CHANGED
        elif "motion_prompt" in fields:
            event = InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED
        elif "duration_seconds" in fields:
            event = InvalidationEvent.SCENE_DURATION_CHANGED
        elif "character_ids" in fields:
            event = InvalidationEvent.SCENE_CHARACTERS_CHANGED
        elif "image_model" in fields:
            event = InvalidationEvent.SCENE_IMAGE_MODEL_CHANGED
        elif "video_model" in fields:
            event = InvalidationEvent.SCENE_VIDEO_MODEL_CHANGED
        flags = effects_for(event) if event else {"image": False, "video": False, "render": True}
        updates = dict(fields)
        if flags["image"]:
            updates["image_stale"] = True
        if flags["video"]:
            updates["video_stale"] = True
        version = self._fork_version(scene, **updates)
        if flags["render"]:
            self._stale_renders(scene.project_id)
        current.model_dump()  # keep current in history
        return version

    def lock_scene(self, user_id: str, scene_id: str, locked: bool = True) -> Scene:
        scene = self._require_scene(user_id, scene_id)
        scene.locked = locked
        return scene

    def delete_scene(self, user_id: str, scene_id: str) -> None:
        scene = self._require_scene(user_id, scene_id)
        if scene.locked:
            raise SceneLockedError("unlock the scene before deleting")
        del self.repo.scenes[scene_id]
        remaining = self.repo.scenes_for(scene.project_id)
        for index, item in enumerate(remaining):
            item.order_index = index
        self._stale_renders(scene.project_id)

    def duplicate_scene(self, user_id: str, scene_id: str) -> Scene:
        scene = self.repo.scenes[scene_id]
        version = self._active_version(scene)
        return self.add_scene(
            user_id,
            scene.project_id,
            visual_prompt=version.visual_prompt,
            motion_prompt=version.motion_prompt,
            character_ids=list(version.character_ids),
            duration_seconds=version.duration_seconds,
            narration=version.narration,
            dialogue=version.dialogue,
            image_model=version.image_model,
            video_model=version.video_model,
        )

    def reorder_scenes(self, user_id: str, project_id: str, ordered_ids: list[str]) -> None:
        self._require_project(user_id, project_id)
        scenes = {s.id: s for s in self.repo.scenes_for(project_id)}
        if set(ordered_ids) != set(scenes):
            raise ProductError("reorder must include every scene once")
        for index, scene_id in enumerate(ordered_ids):
            scenes[scene_id].order_index = index
        flags = effects_for(InvalidationEvent.SCENE_REORDERED)
        if flags["render"]:
            self._stale_renders(project_id)

    def restore_scene_version(self, user_id: str, scene_id: str, version_id: str) -> Scene:
        scene = self.repo.scenes[scene_id]
        self._require_project(user_id, scene.project_id)
        version = self.repo.scene_versions[version_id]
        if version.scene_id != scene.id:
            raise ProductError("version does not belong to scene")
        scene.active_version_id = version_id
        self._stale_renders(scene.project_id)
        return scene

    def plan_project(
        self,
        user_id: str,
        project_id: str,
        *,
        animate_scene_ids: set[str] | None = None,
        kind: str = "full_project",
        scene_id: str | None = None,
    ):
        project = self._require_project(user_id, project_id)
        if kind == "full_project" and not self.repo.scenes_for(project_id):
            self.ensure_mock_outline(user_id, project_id)
        if kind == "scene_video" and scene_id:
            animate_scene_ids = {scene_id}
        versions = self.repo.active_versions(project_id)
        if kind == "scene_image" and scene_id:
            versions = [v for v in versions if v.scene_id == scene_id]
        if kind == "scene_video" and scene_id:
            versions = [v for v in versions if v.scene_id == scene_id]
        items = default_plan_items(
            versions, animate_scene_ids=animate_scene_ids, policy=self.pricing
        )
        if kind == "scene_image":
            items = [i for i in items if i.type is PlanItemType.STILL]
        if kind == "scene_video":
            items = [i for i in items if i.type is PlanItemType.VIDEO]
        if kind == "render":
            items = [i for i in items if i.type is PlanItemType.RENDER]
        plan = assemble_plan(project, versions, items)
        if plan.estimated_provider_usd - 1e-9 > self.limits.max_provider_usd_per_job:
            raise LimitExceededError("provider cost cap exceeded")
        self.repo.plans[plan.id] = plan
        project.status = ProjectStatus.PLANNED
        project.updated_at = self.clock()
        return plan

    def _plan_versions(self, project_id: str, plan: GenerationPlan) -> list:
        versions = self.repo.active_versions(project_id)
        if plan.scoped_scene_ids:
            allowed = set(plan.scoped_scene_ids)
            versions = [v for v in versions if v.scene_id in allowed]
        return versions

    def quote_project(self, user_id: str, project_id: str, plan_id: str) -> StarQuote:
        project = self._require_project(user_id, project_id)
        plan = self.repo.plans[plan_id]
        if plan.project_id != project_id:
            raise OwnershipError("plan does not belong to project")
        current = assemble_plan(
            project,
            self._plan_versions(project_id, plan),
            plan.items,
        )
        if current.plan_hash != plan.plan_hash:
            raise QuoteError("settings changed; requote required")
        now = self.clock()
        quote = StarQuote(
            project_id=project_id,
            user_id=user_id,
            generation_plan_id=plan.id,
            generation_plan_hash=plan.plan_hash,
            quote_hash=hash_quote(plan.plan_hash, plan.customer_stars, self.pricing.policy_id),
            stars=plan.customer_stars,
            estimated_provider_usd=plan.estimated_provider_usd,
            created_at=now,
            expires_at=now + timedelta(seconds=self.limits.quote_ttl_seconds),
        )
        self.repo.quotes[quote.id] = quote
        project.status = ProjectStatus.QUOTED
        return quote

    def _expire_quote(self, quote: StarQuote) -> None:
        if quote.status is QuoteStatus.OPEN and self.clock() >= quote.expires_at:
            quote.status = QuoteStatus.EXPIRED

    def confirm_telegram_payment(
        self,
        user_id: str,
        *,
        quote_id: str,
        telegram_payment_id: str,
        stars: int,
        invoice_payload: str = "",
    ) -> TelegramPayment:
        """Server-confirmed payment only. Client payment_success is ignored."""
        quote = self.repo.quotes[quote_id]
        if quote.user_id != user_id:
            raise OwnershipError("quote does not belong to user")
        self._expire_quote(quote)
        if quote.status is QuoteStatus.EXPIRED:
            raise QuoteError("quote expired")
        if quote.stars != stars:
            raise QuoteError("payment stars do not match quote")
        existing = self.repo.payments_by_telegram.get(telegram_payment_id)
        if existing:
            return self.repo.payments[existing]
        payment = TelegramPayment(
            user_id=user_id,
            quote_id=quote_id,
            telegram_payment_id=telegram_payment_id,
            stars=stars,
            status=PaymentStatus.CONFIRMED,
            invoice_payload=invoice_payload,
        )
        stored = self.repo.put_payment(payment)
        if stored.id != payment.id:
            stored.status = PaymentStatus.DUPLICATE
            return stored
        self.repo.put_transaction(
            StarTransaction(
                user_id=user_id,
                project_id=quote.project_id,
                type=StarTxnType.PURCHASE,
                telegram_payment_id=telegram_payment_id,
                stars=stars,
                idempotency_key=f"payment:{telegram_payment_id}",
                status=LedgerStatus.POSTED,
            )
        )
        quote.status = QuoteStatus.AUTHORIZED
        return stored

    def authorize_generation(self, user_id: str, quote_id: str, payment_id: str) -> GenerationJob:
        quote = self.repo.quotes[quote_id]
        if quote.user_id != user_id:
            raise OwnershipError("quote does not belong to user")
        self._expire_quote(quote)
        if quote.status not in {QuoteStatus.AUTHORIZED, QuoteStatus.CONSUMED}:
            raise AuthorizationError("quote is not payment-authorized")
        payment = self.repo.payments[payment_id]
        if payment.status is not PaymentStatus.CONFIRMED or payment.quote_id != quote_id:
            raise AuthorizationError("payment does not authorize this quote")
        for job in self.repo.jobs.values():
            if job.payment_id == payment_id:
                return job
        active = self.repo.active_jobs_for_user(user_id)
        if len(active) >= self.limits.max_concurrent_jobs_per_user:
            raise LimitExceededError("max concurrent jobs exceeded")
        project_active = self.repo.active_jobs_for_project(quote.project_id)
        if len(project_active) >= self.limits.max_concurrent_jobs_per_project:
            raise LimitExceededError("max concurrent jobs for project exceeded")
        hour_ago = self.clock() - timedelta(hours=1)
        recent = [j for j in self.repo.jobs_for_user(user_id) if j.created_at >= hour_ago]
        if len(recent) >= self.limits.max_generations_per_hour:
            raise LimitExceededError("hourly generation limit exceeded")
        project = self._require_project(user_id, quote.project_id)
        plan = self.repo.plans[quote.generation_plan_id]
        live_hash = assemble_plan(
            project,
            self._plan_versions(project.id, plan),
            plan.items,
        ).plan_hash
        if live_hash != quote.generation_plan_hash:
            raise QuoteError("plan changed after quote; requote")
        gate = self.moderation.check_generation_eligibility(project.prompt)
        if not gate.allowed:
            raise ProductError(gate.reason or "generation ineligible")
        if quote.estimated_provider_usd - 1e-9 > self.limits.max_provider_usd_per_job:
            raise LimitExceededError("provider cost cap exceeded")
        job = GenerationJob(
            project_id=project.id,
            user_id=user_id,
            quote_id=quote.id,
            plan_hash=quote.generation_plan_hash,
            status=JobStatus.WAITING_FOR_PAYMENT,
            authorized=True,
            payment_id=payment_id,
            estimated_provider_cost=quote.estimated_provider_usd,
            provider_cost_cap=self.limits.max_provider_usd_per_job,
            reserved_provider_cost=quote.estimated_provider_usd,
            progress={
                "script": {"completed": 0, "total": 1},
                "images": {"completed": 0, "total": len(self.repo.scenes_for(project.id))},
                "video": {"completed": 0, "total": 0},
                "audio": {"completed": 0, "total": 1},
                "render": {"completed": 0, "total": 1},
            },
            created_at=self.clock(),
            updated_at=self.clock(),
        )
        self.repo.jobs[job.id] = job
        self.repo.put_transaction(
            StarTransaction(
                user_id=user_id,
                project_id=project.id,
                generation_job_id=job.id,
                type=StarTxnType.GENERATION_DEBIT,
                telegram_payment_id=payment.telegram_payment_id,
                stars=quote.stars,
                idempotency_key=f"debit:{payment_id}:{quote.generation_plan_hash}",
            )
        )
        quote.status = QuoteStatus.CONSUMED
        return job

    def payment_for_quote(self, quote_id: str) -> TelegramPayment | None:
        for payment in self.repo.payments.values():
            if payment.quote_id == quote_id and payment.status is PaymentStatus.CONFIRMED:
                return payment
        return None

    def _assert_job_slot(
        self,
        user_id: str,
        project_id: str,
        kind: str,
        scene_id: str | None,
    ) -> None:
        terminal = {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.PARTIAL,
        }
        for job in self.repo.jobs.values():
            if job.user_id != user_id or job.status in terminal:
                continue
            if job.kind == kind and job.project_id == project_id:
                if kind == "full_project" or job.target_scene_id == scene_id:
                    raise JobConflictError("an overlapping job is already active")

    def queue_generation(
        self,
        user_id: str,
        project_id: str,
        quote_id: str,
        *,
        kind: str = "full_project",
        scene_id: str | None = None,
    ) -> GenerationJob:
        self._require_project(user_id, project_id)
        quote = self.repo.quotes.get(quote_id)
        if quote is None or quote.project_id != project_id:
            raise NotFoundError("quote not found")
        if quote.user_id != user_id:
            raise OwnershipError("quote does not belong to user")
        payment = self.payment_for_quote(quote_id)
        if payment is None:
            raise AuthorizationError("payment required")
        existing = next(
            (j for j in self.repo.jobs.values() if j.payment_id == payment.id),
            None,
        )
        if existing is None:
            self._assert_job_slot(user_id, project_id, kind, scene_id)
            job = self.authorize_generation(user_id, quote_id, payment.id)
            job.kind = kind
            job.target_scene_id = scene_id
        else:
            job = existing
        if job.status is JobStatus.WAITING_FOR_PAYMENT:
            self.start_generation(user_id, job.id)
        return job

    def start_generation(self, user_id: str, job_id: str) -> GenerationJob:
        job = self.repo.jobs[job_id]
        if job.user_id != user_id:
            raise OwnershipError("job does not belong to user")
        if not job.authorized or not job.payment_id:
            raise AuthorizationError("generation is not payment-authorized")
        job.status = transition(job.status, JobStatus.QUEUED)
        job.started_at = job.started_at or self.clock()
        job.updated_at = self.clock()
        project = self.repo.projects[job.project_id]
        project.status = ProjectStatus.GENERATING
        return job

    def advance_job(self, job_id: str, nxt: JobStatus) -> GenerationJob:
        job = self.repo.jobs[job_id]
        job.status = transition(job.status, nxt)
        job.updated_at = self.clock()
        return job

    def record_attempt(
        self,
        job_id: str,
        *,
        item_type: PlanItemType,
        provider: str,
        model: str,
        outcome: ProviderOutcome,
        billed: ProviderBilledStatus,
        scene_id: str | None = None,
        error_code: str | None = None,
        status: AttemptStatus | None = None,
        request_hash: str = "",
        remote_operation_id: str | None = None,
        estimated_provider_cost: float = 0.0,
        actual_provider_cost: float | None = None,
        safe_error_message: str | None = None,
    ) -> GenerationAttempt:
        settlement = classify_attempt(outcome=outcome, billed=billed)
        now = self.clock()
        attempt_status = status or (
            AttemptStatus.SUCCEEDED
            if settlement.provider_outcome is ProviderOutcome.SUCCEEDED
            else AttemptStatus.FAILED
            if settlement.provider_outcome is ProviderOutcome.FAILED
            else AttemptStatus.PENDING
        )
        attempt = GenerationAttempt(
            job_id=job_id,
            scene_id=scene_id,
            item_type=item_type,
            provider=provider,
            model=model,
            provider_outcome=settlement.provider_outcome,
            provider_billed=settlement.provider_billed,
            customer_billing=settlement.customer_billing,
            error_code=error_code,
            status=attempt_status,
            request_hash=request_hash,
            remote_operation_id=remote_operation_id,
            estimated_provider_cost=estimated_provider_cost,
            actual_provider_cost=actual_provider_cost,
            started_at=now,
            updated_at=now,
            completed_at=(
                now
                if attempt_status in {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED}
                else None
            ),
            safe_error_message=safe_error_message,
            created_at=now,
        )
        return self.repo.put_attempt(attempt)

    def complete_job(self, job_id: str, *, storage_key: str) -> Render:
        job = self.advance_job(job_id, JobStatus.COMPLETED)
        job.completed_at = self.clock()
        render = Render(project_id=job.project_id, storage_key=storage_key, stale=False)
        self.repo.renders[render.id] = render
        project = self.repo.projects[job.project_id]
        project.status = ProjectStatus.READY
        note = NotificationOutbox(
            user_id=job.user_id,
            project_id=job.project_id,
            job_id=job.id,
            kind="project_ready",
            payload={"text": "Your video is ready.", "open_project": True},
        )
        self.repo.outbox[note.id] = note
        return render

    def fail_job(
        self, job_id: str, *, public_message: str, error_code: str = "GENERATION_FAILED"
    ) -> NotificationOutbox:
        job = self.advance_job(job_id, JobStatus.FAILED)
        job.completed_at = self.clock()
        job.failure_message = public_message
        job.error_code = error_code
        project = self.repo.projects[job.project_id]
        project.status = ProjectStatus.FAILED
        note = NotificationOutbox(
            user_id=job.user_id,
            project_id=job.project_id,
            job_id=job.id,
            kind="generation_failed",
            payload={"text": public_message},
        )
        self.repo.outbox[note.id] = note
        return note

    def recover_uncertain_paid_attempts(self, job_id: str) -> list[GenerationAttempt]:
        """Resume an in-flight provider operation. Never submit a second paid request."""
        recovered: list[GenerationAttempt] = []
        for attempt in self.repo.attempts_for_job(job_id):
            if not attempt.remote_operation_id:
                continue
            if attempt.status not in {AttemptStatus.SUBMITTED, AttemptStatus.RECOVERING_REMOTE}:
                continue
            attempt.status = AttemptStatus.RECOVERING_REMOTE
            attempt.updated_at = self.clock()
            attempt.status = AttemptStatus.SUCCEEDED
            attempt.provider_outcome = ProviderOutcome.SUCCEEDED
            attempt.completed_at = self.clock()
            recovered.append(attempt)
        if recovered:
            job = self.repo.jobs[job_id]
            if job.status is not JobStatus.RECOVERING_REMOTE:
                job.status = transition(job.status, JobStatus.RECOVERING_REMOTE)
                job.updated_at = self.clock()
        return recovered

    def get_job_status(self, user_id: str, job_id: str) -> JobStatusView:
        job = self.repo.jobs.get(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.user_id != user_id:
            raise OwnershipError("job does not belong to user")
        units = []
        for label, counts in job.progress.items():
            units.append(
                {
                    "label": label,
                    "completed": int(counts["completed"]),
                    "total": int(counts["total"]),
                    "done": int(counts["total"]) > 0
                    and int(counts["completed"]) >= int(counts["total"]),
                }
            )
        return JobStatusView(
            id=job.id,
            status=job.status.value,
            units=units,
            authorized=job.authorized,
        )

    def regenerate_scene_image(self, user_id: str, scene_id: str) -> SceneVersion:
        scene = self.repo.scenes[scene_id]
        self._require_project(user_id, scene.project_id)
        snapshots = {
            other.id: (
                self._active_version(other).id,
                self._active_version(other).image_stale,
                self._active_version(other).video_stale,
            )
            for other in self.repo.scenes_for(scene.project_id)
            if other.id != scene_id
        }
        version = self.edit_scene(
            user_id, scene_id, visual_prompt=self._active_version(scene).visual_prompt
        )
        version.image_stale = True
        version.video_stale = True
        for other_id, (version_id, image_stale, video_stale) in snapshots.items():
            other = self._active_version(self.repo.scenes[other_id])
            if other.id != version_id or other.image_stale != image_stale:
                raise ProductError("scene-local regeneration mutated another scene")
            if other.video_stale != video_stale:
                raise ProductError("scene-local regeneration mutated another scene")
        return version

    def regenerate_scene_video(self, user_id: str, scene_id: str) -> SceneVersion:
        scene = self.repo.scenes[scene_id]
        self._require_project(user_id, scene.project_id)
        version = self.edit_scene(
            user_id,
            scene_id,
            motion_prompt=self._active_version(scene).motion_prompt,
        )
        version.image_stale = False
        version.video_stale = True
        return version

    def attach_mock_asset(
        self,
        user_id: str,
        scene_id: str,
        *,
        kind: AssetKind,
        data: bytes,
        model: str = "mock",
    ) -> AssetVersion:
        scene = self.repo.scenes[scene_id]
        self._require_project(user_id, scene.project_id)
        asset = Asset(project_id=scene.project_id, scene_id=scene_id, kind=kind)
        self.repo.assets[asset.id] = asset
        key = f"projects/{scene.project_id}/scenes/{scene_id}/{kind.value}/{new_id()}"
        self.storage.put_bytes(key, data, content_type="application/octet-stream")
        version = AssetVersion(
            asset_id=asset.id,
            storage_key=key,
            sha256=_sha256_bytes(data),
            model=model,
            provider="mock",
        )
        self.repo.asset_versions[version.id] = version
        scene_version = self._active_version(scene)
        if kind is AssetKind.IMAGE:
            scene_version.image_asset_version_id = version.id
            scene_version.image_stale = False
        if kind is AssetKind.VIDEO:
            scene_version.video_asset_version_id = version.id
            scene_version.video_stale = False
        return version

    def project_summary(self, user_id: str, project_id: str) -> ProjectSummary:
        project = self._require_project(user_id, project_id)
        duration = sum(v.duration_seconds for v in self.repo.active_versions(project_id)) or None
        jobs = [j for j in self.repo.jobs.values() if j.project_id == project_id]
        progress = None
        if jobs:
            latest = max(jobs, key=lambda j: j.created_at)
            progress = {
                key: int(val["completed"])
                for key, val in latest.progress.items()
            }
        return ProjectSummary(
            id=project.id,
            title=project.title,
            duration=duration,
            status=project.status.value,
            progress=progress,
            updated_at=project.updated_at.isoformat(),
        )

    def scene_summaries(self, user_id: str, project_id: str) -> list[SceneSummary]:
        self._require_project(user_id, project_id)
        rows: list[SceneSummary] = []
        for scene in self.repo.scenes_for(project_id):
            version = self._active_version(scene)
            rows.append(
                SceneSummary(
                    id=scene.id,
                    order=scene.order_index,
                    duration=version.duration_seconds,
                    characters=list(version.character_ids),
                    status="stale" if version.image_stale or version.video_stale else "ready",
                    production_type=version.production_class,
                    image_model=version.image_model,
                    video_model=version.video_model,
                    can_regenerate=not scene.locked,
                    estimated_regeneration_stars=self.pricing.stars_for_usd(0.45),
                )
            )
        return rows


def freeze_clock(moment: datetime) -> Clock:
    def _clock() -> datetime:
        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)
        return moment
    return _clock
