from datetime import datetime

import luigi

from servicecatalog_puppet import constants, serialisation_utils
from servicecatalog_puppet.serialisation_utils import unwrap
from servicecatalog_puppet.workflow.dependencies import tasks


class DeployC7NPolicies(tasks.TaskWithReferenceAndCommonParameters):
    policies = luigi.DictParameter()
    cachable_level = constants.CACHE_LEVEL_RUN

    def params_for_results_display(self):
        return {
            "task_reference": self.task_reference,
        }

    def run(self):
        policies = dict(policies=[])
        for policy_name, policy in self.policies.items():
            p = unwrap(policy)
            p["mode"]["type"] = "cloudtrail"
            p["mode"][
                "member-role"
            ] = "arn:aws:iam::{account_id}:role/servicecatalog-puppet/c7n/Custodian"
            p["name"] = policy_name
            policies["policies"].append(p)

        bucket = f"sc-puppet-c7n-artifacts-{self.account_id}-{self.region}"
        key = str(datetime.now())
        with self.spoke_regional_client("s3") as s3:
            s3.put_object(
                Bucket=bucket, Key=key, Body=serialisation_utils.dump(unwrap(policies)),
            )
            cached_output_signed_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=60 * 60 * 24,
            )
        regions = "eu-west-1"
        policies_file_url = cached_output_signed_url
        custodian_role_arn = f"arn:aws:iam::{self.account_id}:role/servicecatalog-puppet/c7n/Custodian"  # TODO make dynamic
        parameters_to_use = [
            dict(name="POLICIES_FILE_URL", value=policies_file_url, type="PLAINTEXT",),
            dict(name="REGIONS", value=regions, type="PLAINTEXT",),
            dict(
                name="CUSTODIAN_ROLE_ARN", value=custodian_role_arn, type="PLAINTEXT",
            ),
        ]

        with self.spoke_regional_client("codebuild") as codebuild:
            codebuild.start_build_and_wait_for_completion(
                projectName="servicecatalog-puppet-deploy-c7n",
                environmentVariablesOverride=parameters_to_use,
            )

        self.write_empty_output()
