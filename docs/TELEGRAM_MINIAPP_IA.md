# Mini App information architecture

Phone-first Telegram Mini App. Not a desktop NLE.

## HOME

- Create Video
- My Projects
- Stars / Credits
- Settings

## CREATE

1. Prompt  
2. Characters (0..n, name + description + optional photo)  
3. Video settings (AUTO/FIXED duration, aspect, language, quality; models default Auto)  
4. Review + cost (`Generate — N ⭐`)  
5. Pay / Generate

## PROJECT

- Preview
- Generation status (work units)
- Scene strip (horizontal cards)
- Edit (opens scene inspector)
- Export (canonical storage URL / share later)

## SCENE EDITOR

Tap a card → inspector:

- Preview
- Visual prompt / motion prompt
- Characters
- Image model / video model (Auto unless advanced)
- Regenerate image / regenerate video
- Versions / restore
- Lock

Reorder: drag cards. Duration: simple stepper, not a full timeline.

## WALLET / USAGE

- Purchases (Stars invoices)
- Usage (jobs, stars debited)
- Optional prepaid balance (mechanism B, later)
