import os
import json
import logging
from datetime import date, datetime, timedelta
import requests
import re
import yaml
import base64

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": "token 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"
}

actions_repositories = [
    "bdb-dig-do-pipelines-action-s3",
    "bdb-dig-do-pipelines-action-lambdas-IaC",
    "bdb-dig-do-pipelines-action-ecs-IaC"
]

jobs_to_validate = ["validate-rollback","deploy-backend","deploy-frontend"]

def _get_pipeline_actions_version():

    actions_versions = {}

    for repository in actions_repositories:
        url = f'https://api.github.com/repos/bancodebogota/{repository}/tags'
        response = requests.get(url, headers=headers)
        tags = response.json()
        all_tags = [tag['name'] for tag in tags]
        ultimate_tags = tags = [tag['name'] for tag in tags[:2]]

        regular_expression = r'v[1-9]\b(?!\.\d)'

        for major_tag in all_tags:
            if re.match(regular_expression, major_tag):
                ultimate_tags.insert(0,major_tag)
                break
        actions_versions[repository] = ultimate_tags

    return actions_versions

def _calculate_actions_indicator_value(action, workflow_action_version):

    lastest_action_version = _get_pipeline_actions_version()
    indicator = 0

    s3_tags = {}
    lambda_tags = {}
    ecs_tags = {}

    s3_tags["1"] = lastest_action_version[actions_repositories[0]][0]
    s3_tags["0.66"] = lastest_action_version[actions_repositories[0]][1]
    s3_tags["0.33"] = lastest_action_version[actions_repositories[0]][2]

    lambda_tags["1"] = lastest_action_version[actions_repositories[1]][0]
    lambda_tags["0.66"] = lastest_action_version[actions_repositories[1]][1]
    lambda_tags["0.33"] = lastest_action_version[actions_repositories[1]][2]

    ecs_tags["1"] = lastest_action_version[actions_repositories[2]][0]
    ecs_tags["0.66"] = lastest_action_version[actions_repositories[2]][1]
    ecs_tags["0.33"] = lastest_action_version[actions_repositories[2]][2]

    if action == actions_repositories[0]:
        for key, value in s3_tags.items():
            if value == workflow_action_version:
                indicator = key
                break

    if action == actions_repositories[1]:
        for key, value in lambda_tags.items():
            if value == workflow_action_version:
                indicator = key
                break

    if action == actions_repositories[2]:
        for key, value in ecs_tags.items():
            if value == workflow_action_version:
                indicator = key
                break
    return indicator

def _check_use_validate_rollback(files_content):

    component_type = ["backend.yml","frontend.yml"]
    use_validate_rollback = 0
    count_validate_rollback = 0
    workflow_quantity = 0

    for component in component_type:
        for file_name in files_content:
            if file_name.startswith("requirements") and file_name.endswith(component):
                workflow_quantity=+1
                yaml_content = yaml.safe_load(files_content[file_name])
                if "validate-rollback" in yaml_content['jobs']:
                    count_validate_rollback=+1

    if workflow_quantity == 0:
        use_validate_rollback = 0
    else:
        use_validate_rollback = count_validate_rollback/workflow_quantity

    return use_validate_rollback

def _calculate_pipeline_actions_version_indicator(team):

    repository = "bbog-"+str(team)+"-pipeline"
    initials = ["deploy", "requirements"]
    extensions = ["frontend", "backend","ecs","lambda","mfe"]
    filter_files = []
    files_content = {}
    workflow_actions_version = {}
    pipeline_actions_indicator = {}
    pipeline_actions_indicator_failed = {}
    avg_actions_indicator = {} 

    for action in actions_repositories:
        pipeline_actions_indicator_failed[action] = 0

    try:
        url = f"https://api.github.com/repos/bancodebogota/{repository}/contents/.github/workflows"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            files = response.json()
            files = [file["name"] for file in files]
        else:
            logger.error('Error to get workflows files')
            return pipeline_actions_indicator_failed, 0
    except requests.exceptions.RequestException as e:
        print(f'API Github request error: {e}')

    for filename in files:
        for extension in extensions:
            for initial in initials:
                if filename.startswith(initial) and extension in filename:
                    filter_files.append(filename)

    try:
        for files in filter_files:
            url = f"https://api.github.com/repos/bancodebogota/{repository}/contents/.github/workflows/{files}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                file_content = response.json()
                files_content[file_content["name"]] = base64.b64decode(file_content["content"]).decode('utf-8')
            else:
                logger.error('Error to get content file')
    except requests.exceptions.RequestException as e:
        print(f'API Github request error: {e}')

    for file_name in files_content:
        workflow_actions_version[file_name] = {}
        yaml_content = yaml.safe_load(files_content[file_name])
        for jobs in jobs_to_validate:
            if jobs in yaml_content['jobs']:
                steps = yaml_content.get("jobs", {}).get(jobs,{}).get("steps",[])
                for step in steps:
                    if step.get("uses") == "actions/checkout@v2" or step.get("uses") == "actions/checkout@v3":
                        for action in actions_repositories:
                            if step.get("with", {}).get("repository", {}) == "bancodebogota/"+str(action):
                                if step.get("with", {}).get("ref", {}) == "":
                                    workflow_actions_version[file_name][action] = "N/V"
                                else:
                                    workflow_actions_version[file_name][action] = step.get("with", {}).get("ref", {})

    for file_name in files_content:
        if workflow_actions_version[file_name] == {}:
            if "backend" in file_name:
                if "python" in file_name or "go" in file_name or "nodejs" in file_name:
                    workflow_actions_version[file_name][ actions_repositories[1] ] = "N/V"
                if "java" in file_name or "springboot" in file_name:
                    workflow_actions_version[file_name][ actions_repositories[2] ] = "N/V"
            if "frontend" in file_name or "mfe" in file_name:
                workflow_actions_version[file_name][ actions_repositories[0] ] = "N/V"
            if "lambda" in file_name:
                workflow_actions_version[file_name][ actions_repositories[1] ] = "N/V"
            
            if "ecs" in file_name:
                workflow_actions_version[file_name][ actions_repositories[2] ] = "N/V"
    
    print(workflow_actions_version)
   
    for action in actions_repositories:
        pipeline_actions_indicator[action] = []
        for workflow_to_evaluate in workflow_actions_version:
            if action in workflow_actions_version[workflow_to_evaluate]:
                if workflow_actions_version[workflow_to_evaluate][action] == "N/V":
                    pipeline_actions_indicator[action].append("0")            
                else:
                    pipeline_actions_indicator[action].append(_calculate_actions_indicator_value(action, workflow_actions_version[workflow_to_evaluate][action]))                
                    
    print("Pipelines indicator: ",pipeline_actions_indicator)
    for action in actions_repositories:
        ind = 0
        for i in pipeline_actions_indicator[action]:
            ind = float(ind) + float(i)
        if len(pipeline_actions_indicator[action]) == 0:
            avg_actions_indicator[action] = 1.0
        else:
            avg_actions_indicator[action] = ind/len(pipeline_actions_indicator[action])

    return avg_actions_indicator, _check_use_validate_rollback(files_content)

teams = ["ate"]
for team in teams:
    print(_calculate_pipeline_actions_version_indicator(team))
