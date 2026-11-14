"""Telegram channels a user searches: list, add (with a quality check), re-check, pause, remove."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from jobscout.db.models import TelegramChannel, User
from jobscout.db.session import new_session
from jobscout.pipeline.telegram import apply_stats, channel_stats, ensure_default_channels
from jobscout.scrapers.telegram import ChannelNotFound, TelegramBlocked, normalise_channel
from jobscout.security.ratelimit import limiter
from jobscout.web.auth import current_user

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
Me = Depends(current_user)  # free plan: Telegram is cheap to run (plain web pages, no browser, no AI)
MAX_CHANNELS = 20
CHECKS_PER_HOUR = (30, 3600)  # each check reads ~3 pages from t.me


def _iso(dt):
    return dt.isoformat() if dt else None


def channel_dict(c: TelegramChannel) -> dict:
    return {"id": c.id, "name": c.name, "url": f"https://t.me/s/{c.name}", "title": c.title,
            "subscribers": c.subscribers, "posts_checked": c.posts_checked, "contact_pct": c.contact_pct,
            "posts_per_day": c.posts_per_day, "last_post_at": _iso(c.last_post_at),
            "checked_at": _iso(c.checked_at), "active": c.is_active}


def _own(s, channel_id: int, user: User) -> TelegramChannel:
    row = s.get(TelegramChannel, channel_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "channel not found")
    return row


def _check(name: str, user: User) -> dict:
    if limiter.hit(f"tg-check:{user.id}", *CHECKS_PER_HOUR):
        raise HTTPException(429, "Too many channel checks. Try again later.")
    try:
        return channel_stats(name)
    except ChannelNotFound as e:
        raise HTTPException(404, str(e))
    except TelegramBlocked as e:
        raise HTTPException(503, str(e))
    except OSError:
        raise HTTPException(502, "Couldn't reach Telegram. Check your internet connection.")


@router.get("/channels")
def list_channels(user: User = Me):
    with new_session() as s:
        ensure_default_channels(s, user.id)
        rows = s.scalars(select(TelegramChannel).where(TelegramChannel.user_id == user.id).order_by(TelegramChannel.id))
        return [channel_dict(c) for c in rows]


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)  # "@name", "name" or a t.me link


@router.post("/channels", status_code=201)
def add_channel(body: ChannelIn, user: User = Me):
    try:
        name = normalise_channel(body.name)
    except ChannelNotFound as e:
        raise HTTPException(422, str(e))
    with new_session() as s:
        if s.scalar(select(TelegramChannel.id).where(TelegramChannel.user_id == user.id, TelegramChannel.name == name)):
            raise HTTPException(409, f"@{name} is already in your list.")
        if s.scalar(select(func.count()).select_from(TelegramChannel).where(TelegramChannel.user_id == user.id)) >= MAX_CHANNELS:
            raise HTTPException(422, f"You can have up to {MAX_CHANNELS} channels. Remove one first.")
    stats = _check(name, user)  # outside the DB session: it takes a few seconds
    with new_session() as s:
        row = TelegramChannel(user_id=user.id, name=name)
        apply_stats(row, stats)
        s.add(row)
        s.commit()
        return channel_dict(row)


@router.post("/channels/{channel_id}/check")
def recheck_channel(channel_id: int, user: User = Me):
    with new_session() as s:
        name = _own(s, channel_id, user).name
    stats = _check(name, user)
    with new_session() as s:
        row = _own(s, channel_id, user)
        apply_stats(row, stats)
        s.commit()
        return channel_dict(row)


@router.patch("/channels/{channel_id}")
def set_channel_active(channel_id: int, active: bool, user: User = Me):
    with new_session() as s:
        row = _own(s, channel_id, user)
        row.is_active = active
        s.commit()
        return channel_dict(row)


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, user: User = Me):
    with new_session() as s:
        s.delete(_own(s, channel_id, user))
        s.commit()
