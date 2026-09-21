-- Create unique id constraint for NCM nodes (Neo4j 5+)
CREATE CONSTRAINT ncm_node_id IF NOT EXISTS
FOR (n:NCMNode) REQUIRE n.id IS UNIQUE;
