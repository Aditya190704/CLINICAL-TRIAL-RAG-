from google.cloud import aiplatform
from app.config import settings

aiplatform.init(project=settings.gcp_project, location=settings.gcp_location)

index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
    display_name="clinical-trials-index",
    dimensions=settings.embedding_dim,
    approximate_neighbors_count=50,
    distance_measure_type="DOT_PRODUCT_DISTANCE",
    leaf_node_embedding_count=500,
    leaf_nodes_to_search_percent=10,
    index_update_method="STREAM_UPDATE",
    shard_size="SHARD_SIZE_SMALL",
)
print("INDEX_ID=", index.name)

endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
    display_name="clinical-trials-endpoint", public_endpoint_enabled=True)
print("INDEX_ENDPOINT_ID=", endpoint.name)

endpoint.deploy_index(index=index, deployed_index_id=settings.deployed_index_id,
                      machine_type="e2-standard-2", min_replica_count=1, max_replica_count=1)
print("Deployed. Put INDEX_ID and INDEX_ENDPOINT_ID into backend/.env")