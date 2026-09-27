from __future__ import annotations

from docprod.product.enums import FriendshipStatus, Visibility
from docprod.product.errors import NotFoundError, OwnershipError
from docprod.product.models import Friendship, Project, TelegramUser
from docprod.product.repository import MemoryRepository


def accepted_friend_ids(repo: MemoryRepository, user_id: str) -> set[str]:
    out: set[str] = set()
    for row in repo.friendships.values():
        if row.status != FriendshipStatus.ACCEPTED.value:
            continue
        if row.requester_id == user_id:
            out.add(row.addressee_id)
        elif row.addressee_id == user_id:
            out.add(row.requester_id)
    return out


def can_view_project(repo: MemoryRepository, viewer: TelegramUser, project: Project) -> bool:
    if project.user_id == viewer.id:
        return True
    if project.visibility is Visibility.PUBLIC:
        return True
    if project.visibility is Visibility.FRIENDS:
        friends = accepted_friend_ids(repo, viewer.id)
        return project.user_id in friends or viewer.id in accepted_friend_ids(
            repo, project.user_id
        )
    return False


def require_visible_project(
    repo: MemoryRepository, viewer: TelegramUser, project_id: str
) -> Project:
    project = repo.projects.get(project_id)
    if project is None or not can_view_project(repo, viewer, project):
        raise NotFoundError("project not found")
    return project


def friendship_between(repo: MemoryRepository, a: str, b: str) -> Friendship | None:
    for row in repo.friendships.values():
        if {row.requester_id, row.addressee_id} == {a, b}:
            return row
    return None


def is_blocked(repo: MemoryRepository, a: str, b: str) -> bool:
    row = friendship_between(repo, a, b)
    return row is not None and row.status == FriendshipStatus.BLOCKED.value


def can_cast_linked_user(repo: MemoryRepository, caster_id: str, subject: TelegramUser) -> bool:
    if caster_id == subject.id:
        return True
    if not subject.allow_friends_to_cast_me:
        return False
    row = friendship_between(repo, caster_id, subject.id)
    if row is None or row.status != FriendshipStatus.ACCEPTED.value:
        return False
    return True


def assert_owner(project: Project, user_id: str) -> None:
    if project.user_id != user_id:
        raise OwnershipError("project does not belong to user")
