"""Your businesses: a profile per business you work with, which Ira keeps in mind."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ira.accounts import Principal
from ira.businesses import BusinessError
from ira.channels.deps import get_runtime, require, require_session
from ira.channels.schemas import BusinessChange, BusinessIn, BusinessView, OkResponse
from ira.runtime import Runtime

router = APIRouter(prefix="/v1/me/businesses", tags=["businesses"])


@router.get("", response_model=list[BusinessView], summary="Your business profiles")
def list_businesses(
    who: Principal = Depends(require("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> list[BusinessView]:
    return [BusinessView(**vars(b)) for b in runtime.businesses.list(who.user.id)]


@router.post("", response_model=BusinessView, summary="Add a business profile")
def add_business(
    body: BusinessIn,
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> BusinessView:
    try:
        business = runtime.businesses.add(who.user.id, **body.model_dump())
    except BusinessError as exc:
        raise HTTPException(409, detail=str(exc)) from None
    return BusinessView(**vars(business))


@router.patch("/{business_id}", response_model=BusinessView, summary="Change a business profile")
def change_business(
    business_id: str,
    body: BusinessChange,
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> BusinessView:
    try:
        business = runtime.businesses.change(
            who.user.id, business_id, **body.model_dump(exclude_unset=True)
        )
    except KeyError:
        raise HTTPException(404, detail="no such business") from None
    except BusinessError as exc:
        raise HTTPException(409, detail=str(exc)) from None
    return BusinessView(**vars(business))


@router.delete("/{business_id}", response_model=OkResponse, summary="Remove a business profile")
def remove_business(
    business_id: str,
    who: Principal = Depends(require_session("ask")),
    runtime: Runtime = Depends(get_runtime),
) -> OkResponse:
    if not runtime.businesses.remove(who.user.id, business_id):
        raise HTTPException(404, detail="no such business")
    return OkResponse()
