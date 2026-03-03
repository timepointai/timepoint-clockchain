from fastapi import APIRouter, Depends

from app.core.auth import verify_service_key
from app.core.graph import GraphManager, get_graph_manager
from app.core.tdf_bridge import tdf_to_node_attrs
from app.models.schemas import SubgraphIngestRequest, SubgraphIngestResponse
from timepoint_tdf import TDFRecord

router = APIRouter(dependencies=[Depends(verify_service_key)])


@router.post("/ingest/subgraph", response_model=SubgraphIngestResponse)
async def ingest_subgraph(
    body: SubgraphIngestRequest,
    gm: GraphManager = Depends(get_graph_manager),
):
    node_count = 0
    for node in body.nodes:
        await gm.add_node(
            node.id,
            name=node.name,
            year=node.year,
            month=node.month,
            month_num=node.month_num,
            day=node.day,
            time=node.time,
            country=node.country,
            region=node.region,
            city=node.city,
            slug=node.slug,
            layer=node.layer,
            visibility=node.visibility,
            tags=node.tags,
            one_liner=node.one_liner,
            figures=node.figures,
            source_type=node.source_type,
            confidence=node.confidence,
            source_run_id=node.source_run_id,
            tdf_hash=node.tdf_hash,
        )
        node_count += 1

    edge_count = 0
    for edge in body.edges:
        try:
            await gm.add_edge(
                edge.source,
                edge.target,
                edge.type,
                weight=edge.weight,
                theme=edge.theme,
            )
            edge_count += 1
        except ValueError:
            pass  # skip invalid edge types

    return SubgraphIngestResponse(ingested_nodes=node_count, ingested_edges=edge_count)


@router.post("/ingest/tdf")
async def ingest_tdf(
    records: list[dict],
    gm: GraphManager = Depends(get_graph_manager),
):
    node_count = 0
    for raw in records:
        record = TDFRecord(**raw)
        node_id, attrs = tdf_to_node_attrs(record)
        await gm.add_node(node_id, **attrs)
        node_count += 1
    return {"ingested_nodes": node_count}
