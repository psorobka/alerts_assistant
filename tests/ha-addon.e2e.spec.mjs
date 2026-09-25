import { execFileSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";
import { expect, test } from "@playwright/test";

const port = 18123;
const baseUrl = `http://127.0.0.1:${port}`;
const containerName = `alerts-assistant-e2e-${process.pid}`;
const integrationPath = path.resolve("custom_components/alerts_assistant");
let configPath;
let alertEntityId;

async function waitForHomeAssistant() {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/onboarding`, {
        signal: AbortSignal.timeout(2_000),
      });
      if (response.ok) return;
    } catch {
      // HA needs time to initialize its database and integrations.
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error("Home Assistant did not become ready within 180 seconds");
}

async function post(pathname, body, token) {
  const response = await fetch(`${baseUrl}/${pathname}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Home Assistant ${pathname} returned ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function waitForEntity(token, entityId) {
  const deadline = Date.now() + 120_000;
  let currentEntityIds = [];
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/states`, {
        headers: { authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(2_000),
      });
      if (response.ok) {
        const states = await response.json();
        currentEntityIds = states.map((state) => state.entity_id);
        if (states.some((state) => state.entity_id === entityId)) return;
      }
    } catch {
      // Wait for the configured template entity to be created.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `Home Assistant did not create ${entityId}; current entities: ${currentEntityIds.join(", ")}`,
  );
}

async function prepareHomeAssistant() {
  const status = await (await fetch(`${baseUrl}/api/onboarding`)).json();
  expect(status.every(({ done }) => !done)).toBe(true);

  const clientId = `${baseUrl}/`;
  const { auth_code: userCode } = await post("api/onboarding/users", {
    name: "Alerts Assistant E2E",
    username: `alerts_e2e_${process.pid}`,
    password: "temporary-e2e-password-123",
    client_id: clientId,
    language: "pl",
  });
  const tokenForm = new FormData();
  tokenForm.set("grant_type", "authorization_code");
  tokenForm.set("code", userCode);
  tokenForm.set("client_id", clientId);
  const tokenResponse = await fetch(`${baseUrl}/auth/token`, {
    method: "POST",
    body: tokenForm,
  });
  const tokenData = await tokenResponse.json();
  if (!tokenResponse.ok) throw new Error("Could not authorize the E2E Home Assistant user");
  const { access_token: token } = tokenData;

  await post("api/onboarding/core_config", {}, token);
  await post("api/onboarding/analytics", {}, token);
  await post("api/onboarding/integration", {
    client_id: clientId,
    redirect_uri: `${baseUrl}/onboarding.html?auth_callback=1`,
  }, token);
  await waitForEntity(token, "binary_sensor.e2e_watch");

  let flow = await post("api/config/config_entries/flow", { handler: "alerts_assistant" }, token);
  flow = await post(`api/config/config_entries/flow/${flow.flow_id}`, {}, token);
  expect(flow.type).toBe("create_entry");
  const entryId = flow.result.entry_id;

  let subentryFlow = await post("api/config/config_entries/subentries/flow", {
    handler: [entryId, "alert"],
  }, token);
  subentryFlow = await post(
    `api/config/config_entries/subentries/flow/${subentryFlow.flow_id}`,
    { entity_domain: "binary_sensor" },
    token,
  );
  subentryFlow = await post(
    `api/config/config_entries/subentries/flow/${subentryFlow.flow_id}`,
    { target: ["binary_sensor.e2e_watch"] },
    token,
  );
  expect(subentryFlow.step_id).toBe("user_alert");
  subentryFlow = await post(
    `api/config/config_entries/subentries/flow/${subentryFlow.flow_id}`,
    {
      name: "E2E Leak Alert",
      state: "on",
      notifiers: ["notify.chromium_e2e"],
      repeat: "60",
      can_acknowledge: true,
      ack_from_notification: false,
      skip_first: true,
    },
    token,
  );
  expect(subentryFlow.type).toBe("create_entry");
  await post("api/services/input_boolean/turn_on", {
    entity_id: "input_boolean.e2e_watch",
  }, token);

  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const statesResponse = await fetch(`${baseUrl}/api/states`, {
      headers: { authorization: `Bearer ${token}` },
    });
    const states = await statesResponse.json();
    const alert = states.find((item) => item.entity_id.startsWith("alerts_assistant."));
    if (alert?.state === "on") {
      alertEntityId = alert.entity_id;
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("The configured Alerts Assistant entity did not become active");
}

test.beforeAll(async () => {
  configPath = await mkdtemp(path.join(tmpdir(), "alerts-assistant-ha-e2e-"));
  await writeFile(path.join(configPath, "configuration.yaml"), `
default_config:
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - 127.0.0.1
        - 172.16.0.0/12
      allow_bypass_login: true
    - type: homeassistant
input_boolean:
  e2e_watch:
    name: E2E Watch
template:
  - binary_sensor:
      - name: E2E Watch
        unique_id: e2e_watch
        state: "{{ is_state('input_boolean.e2e_watch', 'on') }}"
lovelace:
  mode: yaml
`);
  await writeFile(path.join(configPath, "ui-lovelace.yaml"), `
title: Alerts Assistant E2E
views:
  - title: Alerty testowe
    path: alerts-e2e
    cards:
      - type: custom:alerts-assistant-card
        title: Test dodatku
`);

  execFileSync("docker", [
    "run", "--detach", "--name", containerName,
    "--publish", `127.0.0.1:${port}:8123`,
    "--volume", `${configPath}:/config`,
    "--volume", `${integrationPath}:/config/custom_components/alerts_assistant:ro`,
    "homeassistant/home-assistant:stable",
  ], { stdio: "ignore" });

  await waitForHomeAssistant();
  await prepareHomeAssistant();
}, 240_000);

test.afterAll(async () => {
  if (!alertEntityId) {
    try {
      execFileSync("docker", ["logs", containerName], { stdio: "inherit" });
    } catch {
      // The container may not have started or may already have exited.
    }
  }
  try {
    execFileSync("docker", ["exec", "--user", "0", containerName, "chmod", "-R", "a+rwX", "/config"], { stdio: "ignore" });
  } catch {
    // The container may not have started or may already have exited.
  }
  try {
    execFileSync("docker", ["rm", "--force", containerName], { stdio: "ignore" });
  } finally {
    if (configPath) await rm(configPath, { recursive: true, force: true });
  }
});

test("real HA loads the installed card and acknowledges its active alert", async ({ page }) => {
  await page.goto(`${baseUrl}/lovelace/alerts-e2e`);

  const card = page.locator("alerts-assistant-card");
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card.locator("h1")).toHaveText("Test dodatku");
  await expect(card.getByText("E2E Leak Alert")).toBeVisible();
  await expect(card.getByText("Aktywny")).toBeVisible();

  await card.getByRole("button", { name: "Potwierdź" }).click();
  await expect(card.getByText("Potwierdzony")).toBeVisible({ timeout: 10_000 });

  await card.getByRole("button", { name: "Uzbrój ponownie" }).click();
  await expect(card.getByText("Aktywny")).toBeVisible({ timeout: 10_000 });
  expect(alertEntityId).toMatch(/^alerts_assistant\./);
});
