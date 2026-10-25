import { defineRailway, project, service, volume } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "poker";
export default defineRailway(() => {
  const calibration = volume("poker-volume", { sizeMB: 5000, region: "europe-west4-drams3a" });
  const poker = service("poker", {
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "infra/railway/Dockerfile" },
    healthcheck: "/health",
    healthcheckTimeout: 300,
    replicas: { "europe-west4-drams3a": 1 },
    volumeMounts: { "/data": calibration },
  });

  return project("zeros-poker-lab", {
    variables: { managed: false },
    resources: [poker, calibration],
  });
});
