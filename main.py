from fastapi import FastAPI, Query, Depends, HTTPException, status, Request
from SPARQLWrapper import SPARQLWrapper, CSV, JSON
from fastapi.middleware.cors import CORSMiddleware
import json
import logging

from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import jwt, JWTError
import httpx


app = FastAPI(root_path="/api/")

origins = [
    "http://localhost",  # Add specific origins if you don't want to allow all
    "http://localhost:8080",
    "http://127.0.0.1",
    "http://127.0.0.1:8080",
    "*", # Allow all origins (use with caution in production)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

sparql = SPARQLWrapper("http://w3id.org/hacid/cs/sparql")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Returns all classes in the knowledge graph
@app.get("/knowledge-graph/classes")
def find_classes():
    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?class ?classLabel WHERE
    {
        ?class rdf:type owl:Class .
        ?class rdfs:label ?classLabel. 
        FILTER(?class != owl:Thing && ?class != owl:Nothing && !isBlank(?class)).
    }
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results['results']['bindings']

# Returns instances of a given class in the knowledge graph
# param class_uri: The URI of the class to find instances for
# param startswith: Optional filter to return only instances whose labels start with this string
# param contains: Optional filter to return only instances whose labels contain these comma-separated substrings

@app.get("/knowledge-graph/instances")
def find_class_instances(class_uri: str, startswith: str|None = None, contains: str | None = None):
    startswith_filter = ""
    contains_filter = ""

    if(startswith!=None):
        startswith_filter = f"FILTER(STRSTARTS(LCASE(?classInstanceLabel), LCASE('{startswith}')))." if startswith else ""

    if(contains!=None):
        contains_filter = "\n".join([f"FILTER CONTAINS(LCASE(str(?classInstanceLabel)), LCASE('{c}'))." for c in (contains.split(',') or [])])

    query = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?classInstance ?classInstanceLabel WHERE {{
        ?classInstance a <{class_uri}> .
        ?classInstance rdfs:label ?classInstanceLabel .
        {startswith_filter}
        {contains_filter}
        FILTER(lang(?classInstanceLabel) = "en-gb" || lang(?classInstanceLabel) = "en-us" || lang(?classInstanceLabel) = "en")
    }} LIMIT 1000
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results['results']['bindings']


# Returns role instances of a given class in the knowledge graph
# param class_uri: The URI of the class to find instances for
# param startswith: Optional filter to return only instances whose labels start with this string
# param contains: Optional filter to return only instances whose labels contain these comma-separated substrings
# NOTE: thid method is no longer used. Now roles are retrieved via the /knowledge-graph/task-data endpoint

@app.get("/knowledge-graph/roles")
def find_roles(class_uri: str, startswith: str|None = None, contains: str | None = None ):
    startswith_filter = ""
    contains_filter = ""

    if(startswith!=None):
        startswith_filter = f"FILTER(STRSTARTS(LCASE(?classInstanceLabel), LCASE('{startswith}')))." if startswith else ""

    if(contains!=None):
        contains_filter = "\n".join([f"FILTER CONTAINS(LCASE(str(?classInstanceLabel)), LCASE('{c}'))." for c in (contains.split(',') or [])])

    query = f"""
BASE <https://w3id.org/hacid/data/cs/wf/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX top: <https://w3id.org/hacid/onto/top-level/>
PREFIX method_role: <app-profile/roles/Method>
PREFIX ops: <ops/>

SELECT DISTINCT
    ?classInstance ?classInstanceLabel
WHERE {{
    {{
        <{class_uri}> top:hasExpectedType  ?range_class.
        ?classInstance a ?range_class ;
              rdfs:label ?classInstanceLabel .
    }} UNION {{
        FILTER (<{class_uri}> = <https://w3id.org/hacid/data/cs/wf/app-profile/roles/Method>)
        {{
            ?op top:isRealizedByMethod ?classInstance .
        }} UNION {{
			?op top:isSpecializedBy ?classInstance.
			FILTER(?op != ops:FilterClimateProjections)
        }} UNION {{
			?op top:isRealizedByPlan/top:definesTask/top:executedThroughOperation ?classInstance.
			FILTER NOT EXISTS {{?other_op1 top:isRealizedByMethod|top:isSpecializedBy ?classInstance}}
			FILTER NOT EXISTS {{?classInstance top:isRealizedByMethod|top:isSpecializedBy|(top:isRealizedByPlan/top:definesTask/top:executedThroughOperation) ?other_op2}}
			FILTER (?op != ops:ClimateDataCollection)
			FILTER (?op != ops:ClimateProjectionSelection)
			FILTER (?op != ops:ClimateServiceCaseResolution)
        }}
		?op rdfs:label ?op_label.
		?classInstance rdfs:label ?method_label.
		BIND(CONCAT(?op_label, ' - ', ?method_label) AS ?classInstanceLabel)
    }}
    
    {startswith_filter}
    {contains_filter}
 
    }}ORDER BY ?classInstanceLabel LIMIT 1000
"""
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results['results']['bindings']

# Returns resources for a given role in the knowledge graph. Internal function to be called by outfacing functions
# param role_uri: the role URI
# param startswith: Optional filter to return only instances whose labels start with this string
# param contains: Optional filter to return only instances whose labels contain these comma-separated substrings
# param output_var_name: Optional specification of the output variable name, defaults to 'classInstance'
def list_resources_for_role(
    role_uri: str,
    startswith: str | None = None,
    contains: str | None = None,
    output_var_name: str = "classInstance"
):
    startswith_filter = ""
    contains_filter = ""

    if(role_uri!='method'):
        if(startswith!=None):
            startswith_filter = f"FILTER(STRSTARTS(LCASE(?{output_var_name}Label), LCASE('{startswith}')))." if startswith else ""

        if(contains!=None):
            contains_filter = "\n".join([f"FILTER CONTAINS(LCASE(str(?{output_var_name}Label)), LCASE('{c}'))." for c in (contains.split(',') or [])])

        query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX top: <https://w3id.org/hacid/onto/top-level/> 

            SELECT DISTINCT
                ?{output_var_name} ?{output_var_name}Label
            WHERE {{
                <{role_uri}>
                    top:hasExpectedType/(
                        (owl:unionOf|owl:intersectionOf)/rdf:rest*/rdf:first |
                        owl:allValuesFrom
                    )* ?itemClass.
                FILTER(?itemClass NOT IN (top:Interval)).
                {{
                    ?{output_var_name} a ?itemClass.
                }} UNION {{
                    ?itemClass
                        a owl:Restriction;
                        owl:onProperty ?p;
                        owl:hasValue ?o
                    .
                    ?{output_var_name} ?p ?o.
                }}.
                ?{output_var_name} rdfs:label ?{output_var_name}Label
                {startswith_filter}
                {contains_filter}
            }}
            ORDER BY ?{output_var_name}Label
            LIMIT 1000
        """
    else:
        if(startswith!=None):
            startswith_filter = f"FILTER(STRSTARTS(LCASE(?{output_var_name}Label), LCASE('{startswith}')))." if startswith else ""

        if(contains!=None):
            contains_filter = "\n".join([f"FILTER CONTAINS(LCASE(str(?{output_var_name}Label)), LCASE('{c}'))." for c in (contains.split(',') or [])])

        query = f"""
            BASE <https://w3id.org/hacid/data/cs/wf/>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX top: <https://w3id.org/hacid/onto/top-level/>
            PREFIX methods: <https://w3id.org/hacid/data/cs/wf/methods/>

            SELECT 
                ?{output_var_name} ?{output_var_name}Label
            WHERE {{
                {{  
                    SELECT
                        ?{output_var_name}
                        ?general_method_label
                        ?general_method_base_label
                        ?specific_method_base_label
                        (GROUP_CONCAT(DISTINCT ?specific_method_alt_label; separator=", ") AS ?specific_method_alt_labels)
                    WHERE {{
                        {{
                            SELECT
                                ?general_method
                                ?general_method_base_label
                                (GROUP_CONCAT(DISTINCT ?general_method_alt_label; separator=", ") AS ?general_method_alt_labels)
                            WHERE {{
                                ?general_method top:specializes methods:ClimateCaseMethod;
                                    rdfs:label ?general_method_base_label.
                                _:some_resource top:specializes ?general_method.
                                OPTIONAL {{
                                    ?general_method top:altLabel ?general_method_alt_label
                                }}
                            }}
                            GROUP BY ?general_method ?general_method_base_label
                        }}
                        BIND(CONCAT(?general_method_base_label, IF(?general_method_alt_labels, CONCAT(' (',?general_method_alt_labels,')'), '')) AS ?general_method_label)
                        {{
                            {{
                                VALUES ?specific_method_base_label {''}
                                BIND(?general_method AS ?{output_var_name})
                            }}
                            UNION
                            {{
                                ?{output_var_name} top:specializes ?general_method;
                                    rdfs:label ?specific_method_base_label.
                                OPTIONAL {{
                                    ?{output_var_name} top:altLabel ?specific_method_alt_label
                                }}
                            }}
                        }}
                    }}
                    GROUP BY ?{output_var_name} ?general_method_base_label ?general_method_label ?specific_method_base_label
                }}
                BIND(CONCAT(?specific_method_base_label, IF(?specific_method_alt_labels, CONCAT(' (',?specific_method_alt_labels,')'), '')) AS ?specific_method_label)
                BIND(IF(?specific_method_label, CONCAT(?general_method_base_label, ' - ', ?specific_method_label), ?general_method_label) AS ?{output_var_name}Label)
                {contains_filter}
            }}
            ORDER BY ?{output_var_name}Label
        """

    #logger.info(f"Query: {query}")
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results['results']['bindings']


# Returns resources for a given role in the knowledge graph
# param role: the role URI
# param startswith: Optional filter to return only instances whose labels start with this string
# param contains: Optional filter to return only instances whose labels contain these comma-separated substrings
@app.get("/knowledge-graph/task-data")
def list_resources_for_generic_role(entity_type: str, startswith: str |None = None, contains: str | None = None):
    return list_resources_for_role(role_uri=entity_type, startswith=startswith, contains=contains)


# Returns all tasks in the knowledge graph
# Currently reads from a static JSON file. To be replaced with SPARQL query in the future.
@app.get("/knowledge-graph/tasks")
def get_tasks():
    with open("data/tasks.json", "r") as f:
        data = json.load(f)
    return data


# Returns all hazards in the knowledge graph
# param startswith: Optional filter to return only hazards whose labels start with this string
# param contains: Optional filter to return only hazards whose labels contain these comma-separated substrings
@app.get("/knowledge-graph/hazards")
def find_hazards(startswith: str|None = None, contains: str | None = None):
    contains_filter = ""
    if(contains!=None):
        contains_filter = "\n".join([f"FILTER CONTAINS(LCASE(str(?{output_var_name}Label)), LCASE('{c}'))." for c in (contains.split(',') or [])])

    query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX top: <https://w3id.org/hacid/onto/top-level/> 

        SELECT DISTINCT
            ?hazard ?hazardLabel
        WHERE {{
            <https://w3id.org/hacid/data/cs/wf/ops/IdentifyHazards/associated-data>
                top:hasExpectedType/(
                    (owl:unionOf|owl:intersectionOf)/rdf:rest*/rdf:first |
                    owl:allValuesFrom
                )* ?itemClass.
            FILTER(?itemClass NOT IN (top:Interval)).
            {{
                ?hazard a ?itemClass.
            }} UNION {{
                ?itemClass
                    a owl:Restriction;
                    owl:onProperty ?p;
                    owl:hasValue ?o
                .
                ?hazard ?p ?o.
            }}.
            ?hazard rdfs:label ?hazardLabel
            FILTER(LCASE(str(?hazardLabel)) != "climate hazard type")
            {contains_filter}
        }}
        ORDER BY ?hazardLabel
        LIMIT 1000
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results['results']['bindings']

@app.get("/knowledge-graph/sparql")
def find_class_instances(query: str):
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return results
