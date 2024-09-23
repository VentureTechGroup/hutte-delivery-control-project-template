import argparse
import subprocess
import json
import os
import xmltodict
import concurrent.futures

SFDX_AUTH_FILE_NAME = "authFile"
PACKAGE_XML_FILE_NAME = "package"
PACKAGE_COMPONENT_THRESHOLD = 2500
EXCLUDED_MTD_TYPES = [
    "ReportType",
    "Report",
    "Translations",
    "CustomObjectTranslation",
    "GlobalValueSetTranslation",
    "StandardValueSetTranslation",
    "CustomFieldTranslation"
]
PARTIAL_PACKAGES_DIR = "partial_packages"

def retrieve_package(package_to_retrieve):
    run_bash(f'sf project retrieve start --manifest {package_to_retrieve} --ignore-conflicts')


def run_bash(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, shell=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(e.stderr)
        raise Exception(e.stderr)

    return result


def pre_script():
    parser = argparse.ArgumentParser()
    parser.add_argument("sfdx_auth_url", type=str)
    args = parser.parse_args()

    sfdx_auth_url_file_content = {"result": {"sfdxAuthUrl": args.sfdx_auth_url}}
    with open(f"{SFDX_AUTH_FILE_NAME}.json", "w") as file:
        json.dump(sfdx_auth_url_file_content, file)

    auth_result = run_bash(
        "sf org login sfdx-url --alias sfdc --set-default --sfdx-url-file authFile.json"
    )
    username = auth_result.stdout.removeprefix("Successfully authorized ").split(" ")[0]
    run_bash(f"sf config set target-org {username}")


def post_script():
    os.remove(f"{SFDX_AUTH_FILE_NAME}.json")


def get_partial_packages():
    with open(f"{PACKAGE_XML_FILE_NAME}.xml", "r") as file:
        data = file.read()

    metadata_types = xmltodict.parse(data, force_list="members")["Package"]["types"]

    partial_packages = []
    current_package = {}
    current_member_count = 0

    for metadata_type in metadata_types:
        if metadata_type not in EXCLUDED_MTD_TYPES:
            type_name = metadata_type["name"]
            members = metadata_type["members"]

            for member in members:
                # Create partial package if threshold is met
                if current_member_count == PACKAGE_COMPONENT_THRESHOLD:
                    current_member_count = 0
                    partial_packages.append(current_package)
                    current_package = {}

                if type_name not in current_package:
                    current_package[type_name] = []

                current_package[type_name].append(member)

                current_member_count += 1

    # Add the last package if it has any content
    if current_package:
        partial_packages.append(current_package)

    return partial_packages


def prepare_for_xmltodict(input_dict: dict):
    result = {
        "Package": {"@xmlns": "http://soap.sforce.com/2006/04/metadata", "types": []}
    }

    for type_name, members in input_dict.items():
        result["Package"]["types"].append({"members": members, "name": type_name})

    return result


def main():
    run_bash(
        f"sf project generate manifest --from-org sfdc --name {PACKAGE_XML_FILE_NAME}"
    )

    partial_packages = get_partial_packages()
    print(f"Retrieving {len(partial_packages)} partial packages...")

    packages_to_retrieve = []

    index = 1
    for partial_package in partial_packages:
        package_file_name = f"{PACKAGE_XML_FILE_NAME}_{index}.xml"
        with open(package_file_name, "w") as file:
            file.write(
                xmltodict.unparse(prepare_for_xmltodict(partial_package), pretty=True)
            )

        packages_to_retrieve.append(package_file_name)
        index += 1


    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.map(retrieve_package, packages_to_retrieve)

    os.remove(f"{PACKAGE_XML_FILE_NAME}.xml")
    for package_to_retrieve in packages_to_retrieve:
        os.remove(package_to_retrieve)


if __name__ == "__main__":
    pre_script()
    main()
    post_script()
