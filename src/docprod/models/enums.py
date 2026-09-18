from enum import StrEnum


class AssetStrategy(StrEnum):
    archive_video = "archive_video"
    archive_image = "archive_image"
    stock_video = "stock_video"
    stock_image = "stock_image"
    ai_image = "ai_image"
    ai_image_to_video = "ai_image_to_video"
    generated_graphic = "generated_graphic"
    map = "map"
    document = "document"
    text_card = "text_card"
    placeholder = "placeholder"


class VisualEffect(StrEnum):
    none = "none"
    slow_push_in = "slow_push_in"
    slow_pull_out = "slow_pull_out"
    pan_left = "pan_left"
    pan_right = "pan_right"
    documentary_handheld = "documentary_handheld"
    parallax_2_5d = "parallax_2_5d"
    surveillance_zoom = "surveillance_zoom"
    photo_table = "photo_table"
    evidence_board = "evidence_board"
    newspaper_reveal = "newspaper_reveal"
    map_route = "map_route"
    silhouette_reveal = "silhouette_reveal"
    circle_highlight = "circle_highlight"
    arrow_annotation = "arrow_annotation"
    location_date_card = "location_date_card"
    cctv_treatment = "cctv_treatment"
    police_light_flicker = "police_light_flicker"


class TransitionType(StrEnum):
    cut = "cut"
    crossfade = "crossfade"
    dip_to_black = "dip_to_black"
    flash = "flash"


class Mood(StrEnum):
    neutral = "neutral"
    tense = "tense"
    ominous = "ominous"
    mysterious = "mysterious"
    urgent = "urgent"
    sad = "sad"
    hopeful = "hopeful"
    triumphant = "triumphant"
    chaotic = "chaotic"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class StageStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
