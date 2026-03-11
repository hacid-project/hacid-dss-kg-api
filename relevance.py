import hashlib
from SPARQLWrapper import SPARQLWrapper, JSON, POST
from rdflib import Graph, Namespace, URIRef, RDF, RDFS, Literal

import logging
logging.basicConfig(
    level=logging.getLevelName("INFO"),  # Set default log level
    encoding='utf-8',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger(__name__)

TOP = Namespace('https://w3id.org/hacid/onto/top-level/')
JDG = Namespace('https://w3id.org/hacid/onto/core/judgement/')
DSSD = Namespace('https://w3id.org/hacid/data/cs/dss/')


def generate_hash_id(string: str) -> str:
    hash = hashlib.md5(string.encode())
    return hash.hexdigest()


class KgClient:
    """
    A client for accessing the HACID Knowledge Graph.
    """

    def __init__(self,
                 endpoint_url: str,
                 update_endpoint_url = None,
                 username: str = None,
                 password: str = None):
        """
        Initialize the SPARQL client with an endpoint URL.
        """
        self.endpoint_url = endpoint_url
        self.sparql = SPARQLWrapper(endpoint_url, updateEndpoint=update_endpoint_url)

        if username and password:
            self.sparql.setCredentials(username, password)

    def query(self, sparql_query: str) -> dict:
        """
        Execute a SPARQL query and return results as a dictionary.

        :param sparql_query: SPARQL query string
        :return: Query result as a dictionary
        """
        self.sparql.setQuery(sparql_query)
        self.sparql.setReturnFormat(JSON)

        try:
            return self.sparql.queryAndConvert()
        except Exception as e:
            LOGGER.error(f"SPARQL query error: {e}")
            raise RuntimeError(f"SPARQL query execution failed: {e}")

    def ask(self, sparql_query: str) -> bool:
        """
        Execute a SPARQL ASK query and return a boolean result.

        :param sparql_query: SPARQL ASK query string
        :return: Boolean result of the ASK query
        """
        self.sparql.setQuery(sparql_query)
        self.sparql.setReturnFormat(JSON)

        try:
            result = self.sparql.queryAndConvert()
            return result.get("boolean", False)
        except Exception as e:
            LOGGER.error(f"SPARQL ASK query error: {e}")
            raise RuntimeError(f"SPARQL ASK query execution failed: {e}")


    def _generate_relevance_triples(self, case_id: str, entity_uri: str, user_id: str, for_delete: bool) -> Graph:
        graph = Graph()

        case_uri = DSSD[f'cases/{case_id}']
        user_uri = DSSD[f'users/{user_id}']

        rel_assignment_id = generate_hash_id(f'{case_uri}-{entity_uri}-{user_uri}-"relevant"')
        rel_assignment_uri = DSSD[f'relevance-statement/{rel_assignment_id}']

        graph.add((rel_assignment_uri, RDF.type, JDG['RelevanceStatement']))
        graph.add((
            rel_assignment_uri,
            RDFS.label,
            Literal(
                f'Relevance statement for entity {entity_uri} in the context of case {case_id} by user {user_id}',
                lang='en')))
        graph.add((rel_assignment_uri, JDG['isJudgementOn'], URIRef(entity_uri)))
        graph.add((rel_assignment_uri, JDG['hasRelevanceContext'], case_uri))
        graph.add((rel_assignment_uri, JDG['hasJudge'], user_uri))

        bin_relevance_uri = DSSD[f'binary-relevance/relevant']
        graph.add((rel_assignment_uri, JDG['hasRelevance'], bin_relevance_uri))

        if not for_delete:
            graph.add((bin_relevance_uri, RDF.type, JDG['BinaryRelevance']))
            graph.add((bin_relevance_uri, RDFS.label, Literal(f'Binary relevance: relevant', lang='en')))
            graph.add((bin_relevance_uri, TOP['hasValue'], URIRef("https://w3id.org/hacid/onto/core/judgement/relevant")))

        return graph

    def create_relevance(self, case_id: str, entity_uri: str, user_id: str):

        case_uri = DSSD[f'cases/{case_id}']
        graph = self._generate_relevance_triples(case_id, entity_uri, user_id, False)

        #insert_query = f'INSERT DATA {{ GRAPH {case_uri.n3()} {{ {graph.serialize(format="nt")} }} }}'

        insert_query = f'INSERT DATA {{ {graph.serialize(format="nt")} }}'

        self.sparql.setMethod(POST)
        self.sparql.setQuery(insert_query)

        try:
            response = self.sparql.query()

            # GraphDB returns 204 on success
            if response.response.status != 204:
                raise RuntimeError(
                    f"SPARQL update failed. HTTP status: {response.response.status}"
                )

            LOGGER.info("Relevance triples successfully inserted")

        except Exception as e:
            raise RuntimeError(
                f"Unexpected error during SPARQL update: {str(e)}"
            ) from e

    def delete_relevance(self, case_id: str, entity_uri: str, user_id: str):

        case_uri = DSSD[f'cases/{case_id}']
        graph = self._generate_relevance_triples(case_id, entity_uri, user_id, True)

        #insert_query = f'DELETE DATA {{ GRAPH {case_uri.n3()} {{ {graph.serialize(format="nt")} }} }}'
        insert_query = f'DELETE DATA {{ {graph.serialize(format="nt")} }}'

        self.sparql.setMethod(POST)
        self.sparql.setQuery(insert_query)

        try:
            response = self.sparql.query()

            # GraphDB returns 204 on success
            if response.response.status != 204:
                raise RuntimeError(
                    f"SPARQL update failed. HTTP status: {response.response.status}"
                )

            LOGGER.info("Relevance triples successfully deleted ")

        except Exception as e:
            raise RuntimeError(
                f"Unexpected error during SPARQL update: {str(e)}"
            ) from e

    def get_relevance_info(self, case_id: str, entity_uri: str) -> list[str]:
        query = f"""
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX jdg: <https://w3id.org/hacid/onto/core/judgement/>
                PREFIX top: <https://w3id.org/hacid/onto/top-level/>

                SELECT DISTINCT ?user ?userId
                WHERE {{
                    ?relevanceStatement a jdg:RelevanceStatement ;
                                        jdg:isJudgementOn <{entity_uri}> ;
                                        jdg:hasRelevanceContext <https://w3id.org/hacid/data/cs/dss/cases/{case_id}> ;
                                        jdg:hasRelevance/top:hasValue <https://w3id.org/hacid/onto/core/judgement/relevant> ;
                                        jdg:hasJudge ?user .
                BIND(REPLACE(STR(?user), "https://w3id.org/hacid/data/cs/dss/users/(.+)", "$1") as ?userId) .
                }} ORDER BY ?userId
                """

        results = self.query(query)

        user_ids = list()
        for result in results["results"]["bindings"]:
            user_ids.append(result['userId']['value'])

        return user_ids



if __name__ == '__main__':

    # in fastapi you can "store" and reuse a kgclient with app.state.KG_CLIENT = KgClient(...)
    kg = KgClient(
        endpoint_url="http://keng.istc.cnr.it:7200/repositories/hacid-cs-write",
        update_endpoint_url="http://keng.istc.cnr.it:7200/repositories/hacid-cs-write/statements")

    # call this from tag_resource
    kg.create_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-1")
    kg.create_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-2")
    kg.create_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-3")
    # call this (without print) from get_tagged_resource_info
    print(kg.get_relevance_info("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity"))
    # call this from untag_resource
    kg.delete_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-1")
    kg.delete_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-2")
    kg.delete_relevance("my-test-case", "https://w3id.org/hacid/data/entity/my-test-entity", "my-test-user-3")