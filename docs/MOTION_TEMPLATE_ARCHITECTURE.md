# Motion template architecture

`MotionTemplate` metadata (empty library for now):

id, name, category, source_type, duration, people_count, orientation, energy, camera_motion, audio_available, rights/source, storage_key, compatible model capabilities.

Categories include argument, door_reveal, awkward_stare, run, dance, celebrate, sit, walk, fight_standoff, phone_reaction.

Reference motion may come from licensed library, VideoForge assets, generated templates, or explicit upload. Customers are not required to perform.

Task class `MOTION_CONTROLLED_PERFORMANCE` prefers Kling Motion Control / Genjutsu **candidates**. Auto-route stays on implemented models until those adapters exist.

`MotionGraphicsSpec` requests cold_open, character_intro, punchline_caption, freeze_frame, transition, episode_title, end_card. Execution: local FFmpeg unless optional Motion Designer backend is explicitly enabled.
