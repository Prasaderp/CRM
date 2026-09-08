import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, request as playwrightRequest, test } from "@playwright/test";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const databaseUrl =
  process.env.TEST_DATABASE_URL ??
  "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test";
const origin = "http://127.0.0.1:5190";
const apiOrigin = "http://127.0.0.1:8019";
const seedApiPort = 8021;
const propertyId = "10000000-0000-4000-8000-000000000027";
const ownerId = "20000000-0000-4000-8000-000000000027";
const secondUserId = "20000000-0000-4000-8000-000000000028";
const password = "Synthetic CRM Passphrase 2026!";
const environment = {
  ...process.env,
  ENVIRONMENT: "local",
  DATABASE_URL: databaseUrl,
  TEST_DATABASE_URL: databaseUrl,
  PUBLIC_ORIGIN: origin,
  CANONICAL_NOTICE_VERSION: "2026-07-30",
  CANONICAL_NOTICE_TEXT: "Synthetic browser-test privacy notice.",
  SMTP_HOST: "127.0.0.1",
  SMTP_PORT: "1025",
  SMTP_SENDER: "browser-test@client.example",
  RECIPIENT_ALLOW_LIST: "browser-recipient@client.example",
};
let inquiryId = "";
let activeProject = false;
const backendPython = path.join(
  repository,
  "backend",
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

function execute(file: string, args: string[], allowed = [0]): string {
  const result = spawnSync(file, args, {
    cwd: repository,
    env: environment,
    encoding: "utf8",
    timeout: 30_000,
  });
  if (result.error || result.status === null || !allowed.includes(result.status)) {
    throw new Error(
      `${file} failed (${result.status ?? "no status"}): ${result.error?.message ?? result.stderr}`,
    );
  }
  return result.stdout.trim();
}

function compose(...args: string[]): string {
  return execute("docker", ["compose", "-f", path.join(repository, "compose.yaml"), ...args]);
}

function psql(sql: string, database = "real_estate_crm_test"): string {
  return compose(
    "exec",
    "-T",
    "postgres",
    "psql",
    "-X",
    "-v",
    "ON_ERROR_STOP=1",
    "-U",
    "postgres",
    "-d",
    database,
    "-Atc",
    sql,
  );
}

function sqlLiteral(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

async function createLead(baseUrl: string): Promise<string> {
  const response = await fetch(`${baseUrl}/api/v1/leads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({
      propertySlug: "phase-27-home",
      formVersion: "phase-27-browser",
      contact: {
        fullName: "Synthetic CRM Customer",
        email: "phase27-customer@example.com",
        phone: "+919876543210",
        preferredContactMethod: "email",
      },
      inquiry: {
        intent: "buy",
        message: "Please arrange a synthetic viewing.",
      },
      attribution: { utmSource: "instagram" },
      consent: {
        privacyNoticeVersion: "ignored-client-value",
        requestedContact: true,
        marketing: false,
        adMeasurement: false,
      },
    }),
  });
  if (response.status !== 201) throw new Error(`lead seed failed: ${response.status}`);
  return String((await response.json()).inquiryId);
}

function startSeedApi(): ChildProcess {
  return spawn(
    backendPython,
    [
      "-m",
      "uvicorn",
      "real_estate_crm.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(seedApiPort),
    ],
    { cwd: repository, env: environment, stdio: "pipe" },
  );
}

async function stopProcess(processHandle: ChildProcess): Promise<void> {
  if (processHandle.exitCode !== null) return;
  if (process.platform === "win32" && processHandle.pid) {
    spawnSync("taskkill", ["/pid", String(processHandle.pid), "/T", "/F"], {
      cwd: repository,
      encoding: "utf8",
      timeout: 5_000,
    });
  } else {
    processHandle.kill();
  }
}

async function waitForSeedApi(): Promise<void> {
  await expect
    .poll(async () => {
      try {
        return (await fetch(`http://127.0.0.1:${seedApiPort}/health/ready`)).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
}

test.beforeAll(async ({ browserName: _browserName }, testInfo) => {
  activeProject = testInfo.project.name === "desktop-chromium";
  if (!activeProject) return;
  compose("up", "-d", "postgres", "mailpit");
  const exists = psql(
    "SELECT 1 FROM pg_database WHERE datname = 'real_estate_crm_test'",
    "postgres",
  );
  if (exists !== "1") {
    compose("exec", "-T", "postgres", "createdb", "-U", "postgres", "real_estate_crm_test");
  }
  execute("uv", [
    "run",
    "--project",
    "backend",
    "alembic",
    "-c",
    "backend/alembic.ini",
    "upgrade",
    "head",
  ]);
  psql(
    "TRUNCATE audit_events, lead_status_history, sessions, users, idempotency_requests, " +
      "outbox_jobs, attribution_touches, consent_records, inquiries, contacts, properties CASCADE",
  );
  const hash = execute("uv", [
    "run",
    "--project",
    "backend",
    "python",
    "-c",
    `from real_estate_crm.auth.service import hash_password; print(hash_password(${JSON.stringify(password)}))`,
  ]);
  psql(
    "INSERT INTO properties " +
      "(id,slug,title,summary,locality,price_label,project_registration_number,registration_authority_url) VALUES " +
      `('${propertyId}','phase-27-home','Phase 27 Test Home','Synthetic CRM browser fixture.','Pune','Test price','TEST-RERA-27','https://example.invalid/registration'); ` +
      "INSERT INTO users (id,normalized_email,display_name,password_hash,role,is_active) VALUES " +
      `('${ownerId}','phase27-admin@example.com','Synthetic Admin',${sqlLiteral(hash)},'admin',true),` +
      `('${secondUserId}','phase27-agent@example.com','Synthetic Agent',${sqlLiteral(hash)},'agent',true)`,
  );
  const seedApi = startSeedApi();
  try {
    await waitForSeedApi();
    inquiryId = await createLead(`http://127.0.0.1:${seedApiPort}`);
  } finally {
    await stopProcess(seedApi);
  }
});

test.afterAll(() => {
  if (!activeProject) return;
  compose("start", "postgres", "mailpit");
  psql(
    "TRUNCATE audit_events, lead_status_history, sessions, users, idempotency_requests, " +
      "outbox_jobs, attribution_touches, consent_records, inquiries, contacts, properties CASCADE",
  );
});

test("login, detail mutations, conflict recovery, audit refresh, and session expiry", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.goto("/login");
  await page.getByLabel("Email").fill("phase27-admin@example.com");
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Inquiries" })).toBeVisible();
  await expect(page.getByText("Synthetic CRM Customer")).toBeVisible();
  expect(page.url()).not.toContain("phase27-customer");

  await page.getByRole("link", { name: "Synthetic CRM Customer" }).click();
  await expect(page.getByRole("heading", { name: "Synthetic CRM Customer" })).toBeVisible();
  await expect(page.getByText("Please arrange a synthetic viewing.")).toBeVisible();

  await page.getByLabel("Current stage").selectOption("qualified");
  await page.getByRole("button", { name: "Save status" }).click();
  await expect(page.locator(".detail-heading .status-pill")).toHaveText("qualified");
  await page.getByLabel("Assigned team member").selectOption(secondUserId);
  await page.getByRole("button", { name: "Save owner" }).click();
  await expect(page.getByLabel("Assigned team member")).toHaveValue(secondUserId);

  const secondSession = await playwrightRequest.newContext({
    baseURL: apiOrigin,
    extraHTTPHeaders: { Origin: origin },
  });
  try {
    const login = await secondSession.post("/api/v1/auth/login", {
      data: { email: "phase27-agent@example.com", password },
    });
    expect(login.status()).toBe(200);
    const state = await secondSession.storageState();
    const csrf = state.cookies.find((cookie) => cookie.name === "csrf_token")?.value;
    expect(csrf).toBeTruthy();
    const current = await secondSession.get(`/api/v1/inquiries/${inquiryId}`);
    const version = Number((await current.json()).version);
    const competing = await secondSession.patch(`/api/v1/inquiries/${inquiryId}/status`, {
      headers: { "X-CSRF-Token": csrf ?? "" },
      data: { status: "contacted", expectedVersion: version },
    });
    expect(competing.status()).toBe(200);

    await page.getByLabel("Current stage").selectOption("won");
    await page.getByRole("button", { name: "Save status" }).click();
    await expect(page.getByText("This inquiry changed in another session.")).toBeVisible();
    await expect(page.getByLabel("Current stage")).toHaveValue("won");
    await page.getByRole("button", { name: "Save status" }).click();
    await expect(page.locator(".detail-heading .status-pill")).toHaveText("won");
    await expect(page.getByText("contacted → won")).toBeVisible();
  } finally {
    await secondSession.dispose();
  }

  const stored = JSON.parse(
    psql(
      "SELECT row_to_json(result) FROM (" +
        "SELECT i.status,i.version,i.assigned_user_id::text AS owner," +
        "(SELECT count(*)::int FROM lead_status_history h WHERE h.inquiry_id=i.id) AS history," +
        "(SELECT count(*)::int FROM audit_events a WHERE a.entity_id=i.id) AS audits " +
        `FROM inquiries i WHERE i.id='${inquiryId}') result`,
    ),
  ) as Record<string, unknown>;
  expect(stored).toMatchObject({
    status: "won",
    owner: secondUserId,
    history: 3,
    audits: 4,
  });

  psql(
    `UPDATE sessions SET idle_expires_at=now()-interval '1 second' WHERE user_id='${ownerId}' AND revoked_at IS NULL`,
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Team sign in" })).toBeVisible();
  expect(page.url()).toBe(`${origin}/login`);
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
});
