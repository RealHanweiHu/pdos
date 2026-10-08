"""Authenticated proposal entry, direct document editing and named investment review."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.product_proposal import ProposalAI
from app.api.ai import get_application_gateway
from app.api.auth import no_store
from app.api.product_workspace import Context, Database, _error
from app.contracts.product_proposals import (
    ProposalAIRequest,
    ProposalCreate,
    ProposalDecide,
    ProposalEdit,
    ProposalSubmit,
)
from app.domain.product_proposals import ProductProposalService

router = APIRouter(
    prefix="/api/product-work/spaces/{space_id}/proposals", tags=["product-proposals"]
)
Gateway = Annotated[ApplicationModelGateway, Depends(get_application_gateway)]


@router.get("")
def list_proposals(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).list(context, space_id)
    except Exception as error:
        raise _error(error) from error


@router.post("", status_code=201)
def create_proposal(
    space_id: UUID, body: ProposalCreate, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).create(context, space_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/{proposal_id}")
def read_proposal(
    space_id: UUID, proposal_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).detail(context, space_id, proposal_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/{proposal_id}/changes")
def change_proposal(
    space_id: UUID,
    proposal_id: UUID,
    body: ProposalEdit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).edit(context, space_id, proposal_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/{proposal_id}/submit")
def submit_proposal(
    space_id: UUID,
    proposal_id: UUID,
    body: ProposalSubmit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).submit(context, space_id, proposal_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/{proposal_id}/decide")
def decide_proposal(
    space_id: UUID,
    proposal_id: UUID,
    body: ProposalDecide,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductProposalService(engine).decide(context, space_id, proposal_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/{proposal_id}/ai")
def edit_with_ai(
    space_id: UUID,
    proposal_id: UUID,
    body: ProposalAIRequest,
    response: Response,
    context: Context,
    engine: Database,
    gateway: Gateway,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProposalAI(engine, gateway).generate(context, space_id, proposal_id, body)
    except Exception as error:
        raise _error(error) from error
