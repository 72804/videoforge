# Multi-model story pipeline

Premium / Max / flagship friend-group (including future Birko 2):

1. **PRIMARY** GPT-6 Astra — multiple treatments / creative direction  
2. **CRITIC** Claude Opus 5.5 — structured script doctor (`CreativeScorecard` + raw critique)  
3. **FINALIZER** GPT-6 Astra — shooting script; useful critique only, never blind obedience  

Balanced: GPT-6 Sol alone. Economy: GPT-6 Luna alone.

Ensemble roles (`PRIMARY_MODEL` / `CRITIC_MODEL` / `FINALIZER_MODEL`) are generic. Persist on `ScriptVersion.story_spec["ensemble"]`: treatments, critic output, final script, model ids, prompt versions. `executed=false` until we generate.

Numeric scorecard is staff-only. Customers do not see internal scores.

Anthropic: official Messages API id `claude-opus-5-5`, worker `ANTHROPIC_API_KEY`. Payload builder only this phase. Key not required for tests.
