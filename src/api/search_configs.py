import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database import get_db
from src.models.search_config import SearchConfig

router = APIRouter(prefix="/api/v1/search-configs", tags=["Search Configs"])


class SearchConfigCreate(BaseModel):
    name: str
    url: str
    search_term: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True


class SearchConfigUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    search_term: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/")
async def list_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SearchConfig).order_by(SearchConfig.created_at))
    return {"configs": [_out(c) for c in result.scalars().all()]}


@router.post("/", status_code=201)
async def create_config(data: SearchConfigCreate, db: AsyncSession = Depends(get_db)):
    config = SearchConfig(**data.model_dump())
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _out(config)


@router.put("/{config_id}")
async def update_config(config_id: str, data: SearchConfigUpdate, db: AsyncSession = Depends(get_db)):
    config = await _get(config_id, db)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(config, k, v)
    await db.commit()
    await db.refresh(config)
    return _out(config)


@router.delete("/{config_id}", status_code=204)
async def delete_config(config_id: str, db: AsyncSession = Depends(get_db)):
    config = await _get(config_id, db)
    await db.delete(config)
    await db.commit()


async def _get(config_id: str, db: AsyncSession) -> SearchConfig:
    try:
        cid = uuid.UUID(config_id)
    except ValueError:
        raise HTTPException(400, "Invalid config ID")
    result = await db.execute(select(SearchConfig).where(SearchConfig.id == cid))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Search config not found")
    return config


def _out(c: SearchConfig) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "url": c.url,
        "search_term": c.search_term,
        "category": c.category,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
