"""Incident detection on an uploaded road video.

An operator picks a road on the map and uploads a clip of it; the clip
stands in for a camera on that road. `analyse.analyse_clip` runs every
detector that is installed over it -- the accident model, the fire/smoke
scorer, and screen-space motion checks on tracked vehicles -- and
`severity.assess` turns each finding into a severity with plain-language
reasons. `worker` consumes `vision.clip-submitted` and answers on
`vision.clip-analysed`; `python -m vision_service.clips` runs it.

A finding is a candidate for an operator (ADR-006). Nothing here dispatches.
"""
