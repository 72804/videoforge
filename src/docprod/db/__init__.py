"""PostgreSQL persistence. Named aliases share one unit-of-work repository."""

from docprod.db.postgres_repo import PostgresRepository

PostgresUserRepository = PostgresRepository
PostgresProjectRepository = PostgresRepository
PostgresCharacterRepository = PostgresRepository
PostgresSceneRepository = PostgresRepository
PostgresAssetRepository = PostgresRepository
PostgresGenerationRepository = PostgresRepository
PostgresBillingRepository = PostgresRepository
PostgresNotificationRepository = PostgresRepository
PostgresIdempotencyRepository = PostgresRepository

__all__ = [
    "PostgresRepository",
    "PostgresUserRepository",
    "PostgresProjectRepository",
    "PostgresCharacterRepository",
    "PostgresSceneRepository",
    "PostgresAssetRepository",
    "PostgresGenerationRepository",
    "PostgresBillingRepository",
    "PostgresNotificationRepository",
    "PostgresIdempotencyRepository",
]
