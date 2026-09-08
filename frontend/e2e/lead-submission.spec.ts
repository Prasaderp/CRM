import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page, test } from "@playwright/test";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const databaseUrl =
  process.env.TEST_DATABASE_URL ??
  "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test";
const syntheticPropertyId = "10000000-0000-4000-8000-000000000019";
const backendPython = path.join(
  repository,
  "backend",
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const environment = {
  ...process.env,
  ENVIRONMENT: "local",
  DATABASE_URL: databaseUrl,
  TEST_DATABASE_URL: databaseUrl,
  PUBLIC_ORIGIN: "http://127.0.0.1:5190",
  CANONICAL_NOTICE_VERSION: "2026-07-30",
  CANONICAL_NOTICE_TEXT: "Synthetic browser-test privacy notice.",
  SMTP_HOST: "127.0.0.1",
  SMTP_PORT: "1025",
  SMTP_SENDER: "browser-test@client.example",
  RECIPIENT_ALLOW_LIST: "browser-recipient@client.example",
};

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

function queryJson(sql: string): Record<string, unknown> {
  const output = psql(`SELECT row_to_json(result) FROM (${sql}) result`);
  if (!output) throw new Error("database assertion returned no row");
  return JSON.parse(output) as Record<string, unknown>;
}

async function fillLead(page: Page, email: string): Promise<void> {
  await page.getByLabel(/Full name/).fill("Synthetic Browser User");
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page.getByRole("textbox", { name: "Phone", exact: true }).fill("+919876543210");
  await page
    .getByRole("combobox", { name: "Inquiry type", exact: true })
    .selectOption("information");
  await page
    .getByRole("combobox", { name: "Preferred contact", exact: true })
    .selectOption("email");
  await page.getByText("Add timing, budget, or a question").click();
  await page.getByLabel("Question or context").fill("Please share a synthetic brochure.");
  await page.getByLabel(/I.m requesting a response/).check();
}

async function waitForOutbox(reference: string, state: string): Promise<Record<string, unknown>> {
  let result: Record<string, unknown> = {};
  await expect
    .poll(
      () => {
        result = queryJson(
          "SELECT o.state, o.attempts, o.last_error_code " +
            "FROM outbox_jobs o JOIN inquiries i ON i.id = o.aggregate_id " +
            `WHERE i.public_reference = '${reference}'`,
        );
        return result.state;
      },
      { timeout: 15_000 },
    )
    .toBe(state);
  return result;
}

function startWorker(): ChildProcess {
  return spawn(
    backendPython,
    ["-m", "real_estate_crm.notifications.worker", "--worker-id", `browser-${Date.now()}`],
    { cwd: repository, env: environment, stdio: "pipe" },
  );
}

function startApi(port: number): ChildProcess {
  return spawn(
    backendPython,
    ["-m", "uvicorn", "real_estate_crm.app:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: repository, env: environment, stdio: "pipe" },
  );
}

async function waitForApi(port: number): Promise<void> {
  await expect
    .poll(async () => {
      try {
        return (await fetch(`http://127.0.0.1:${port}/health/ready`)).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
}

async function stopWorker(worker: ChildProcess): Promise<void> {
  if (worker.exitCode !== null) return;
  if (process.platform === "win32" && worker.pid) {
    spawnSync("taskkill", ["/pid", String(worker.pid), "/T", "/F"], {
      cwd: repository,
      encoding: "utf8",
      timeout: 5_000,
    });
  } else {
    worker.kill();
  }
  await Promise.race([
    new Promise<void>((resolve) => worker.once("exit", () => resolve())),
    new Promise<void>((resolve) => setTimeout(resolve, 2_000)),
  ]);
}

test.beforeAll(() => {
  compose("up", "-d", "postgres", "mailpit");
  const exists = psql(
    "SELECT 1 FROM pg_database WHERE datname = 'real_estate_crm_test'",
    "postgres",
  );
  if (exists !== "1")
    compose("exec", "-T", "postgres", "createdb", "-U", "postgres", "real_estate_crm_test");
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
      "outbox_jobs, attribution_touches, consent_records, inquiries, contacts, properties CASCADE; " +
      "INSERT INTO properties " +
      "(id, slug, title, summary, locality, price_label, project_registration_number, registration_authority_url) " +
      `VALUES ('${syntheticPropertyId}', 'phase-19-home', 'Phase 19 Test Home', ` +
      "'A synthetic listing used only for browser acceptance.', 'Pune', 'Test price', " +
      "'TEST-RERA-19', 'https://example.invalid/registration')",
  );
});

test.afterAll(() => {
  compose("start", "postgres", "mailpit");
  psql(
    "TRUNCATE audit_events, lead_status_history, sessions, users, idempotency_requests, " +
      "outbox_jobs, attribution_touches, consent_records, inquiries, contacts, properties CASCADE",
  );
});

test("mobile keyboard flow commits exactly once and delivers through Mailpit", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await page.goto(
    "/p/phase-19-home?utm_source=instagram&utm_campaign=synthetic%00campaign&fbclid=opaque-test-click&ignored=discard-me",
  );
  await expect(page.getByRole("heading", { name: "Phase 19 Test Home" })).toBeVisible();
  await expect(page.getByLabel("Property disclosure")).toContainText("no scarcity");
  expect((await page.getByLabel("Full name").boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
  await fillLead(page, "mobile-browser@example.com");
  await page.getByRole("button", { name: "Send property enquiry" }).dblclick();
  await expect(page.getByRole("heading", { name: "Thank you." })).toBeVisible();
  const reference = (await page.locator(".reference strong").textContent()) ?? "";
  expect(reference).toMatch(/^RE-[A-Z0-9]{10}$/);

  const stored = queryJson(
    "SELECT count(DISTINCT i.id)::int AS inquiries, count(DISTINCT o.id)::int AS outbox, " +
      "bool_and(c.requested_contact) AS requested_contact, bool_and(NOT c.marketing_opt_in) AS marketing_off, " +
      "max(c.notice_text) AS notice_text, max(a.utm_source) AS source, max(a.utm_campaign) AS campaign, " +
      "max(a.click_id_kind) AS click_kind, max(a.click_id_value) AS click_value, max(a.landing_path) AS landing " +
      "FROM inquiries i JOIN contacts ct ON ct.id=i.contact_id JOIN consent_records c ON c.inquiry_id=i.id " +
      "JOIN attribution_touches a ON a.inquiry_id=i.id JOIN outbox_jobs o ON o.aggregate_id=i.id " +
      "WHERE ct.normalized_email='mobile-browser@example.com'",
  );
  expect(stored).toMatchObject({
    inquiries: 1,
    outbox: 1,
    requested_contact: true,
    marketing_off: true,
    notice_text: "Synthetic browser-test privacy notice.",
    source: "instagram",
    campaign: "syntheticcampaign",
    click_kind: "fbclid",
    click_value: "opaque-test-click",
  });
  expect(String(stored.landing)).not.toContain("?");

  const worker = startWorker();
  try {
    await waitForOutbox(reference, "completed");
    await expect
      .poll(async () => {
        const response = await fetch("http://127.0.0.1:8025/api/v1/messages?limit=50");
        return response.ok && (await response.text()).includes(reference);
      })
      .toBe(true);
  } finally {
    await stopWorker(worker);
  }
});

test("lost response replays the stored 201 with the same idempotency key", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  let attempts = 0;
  const keys: string[] = [];
  await page.route("**/api/v1/leads", async (route) => {
    attempts += 1;
    keys.push(route.request().headers()["idempotency-key"]);
    if (attempts === 1) {
      const committed = await route.fetch();
      expect(committed.status()).toBe(201);
      await route.abort("connectionreset");
      return;
    }
    await route.continue();
  });
  await page.goto("/p/phase-19-home?utm_source=x&twclid=synthetic-twclid");
  await fillLead(page, "retry-browser@example.com");
  await page.getByRole("button", { name: "Send property enquiry" }).click();
  await expect(page.getByRole("alert")).toContainText("Retry without changing it");
  await page.getByRole("button", { name: "Send property enquiry" }).click();
  await expect(page.getByRole("heading", { name: "Thank you." })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(
    queryJson(
      "SELECT count(DISTINCT i.id)::int AS inquiries, count(DISTINCT o.id)::int AS outbox " +
        "FROM contacts c JOIN inquiries i ON i.contact_id=c.id JOIN outbox_jobs o ON o.aggregate_id=i.id " +
        "WHERE c.normalized_email='retry-browser@example.com'",
    ),
  ).toMatchObject({ inquiries: 1, outbox: 1 });
});

test("SMTP outage leaves an accepted lead durably pending", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.goto("/p/phase-19-home");
  await fillLead(page, "smtp-outage@example.com");
  compose("stop", "mailpit");
  await page.getByRole("button", { name: "Send property enquiry" }).click();
  await expect(page.getByRole("heading", { name: "Thank you." })).toBeVisible();
  const reference = (await page.locator(".reference strong").textContent()) ?? "";
  const worker = startWorker();
  try {
    const pending = await waitForOutbox(reference, "pending");
    await expect
      .poll(() =>
        Number(
          queryJson(
            "SELECT o.attempts FROM outbox_jobs o JOIN inquiries i ON i.id=o.aggregate_id " +
              `WHERE i.public_reference='${reference}'`,
          ).attempts,
        ),
      )
      .toBeGreaterThan(0);
    expect(pending.state).toBe("pending");
  } finally {
    await stopWorker(worker);
    compose("start", "mailpit");
  }
});

test("database outage never renders success or creates a partial lead", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.goto("/p/phase-19-home");
  await fillLead(page, "database-outage@example.com");
  compose("stop", "postgres");
  try {
    await page.getByRole("button", { name: "Send property enquiry" }).click();
    await expect(page.getByRole("alert")).toContainText("could not confirm", { timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Thank you." })).toHaveCount(0);
  } finally {
    compose("start", "postgres");
  }
  await expect
    .poll(() => {
      try {
        return queryJson(
          "SELECT count(*)::int AS count FROM contacts WHERE normalized_email='database-outage@example.com'",
        ).count;
      } catch {
        return -1;
      }
    })
    .toBe(0);
});

test("API restart replays the committed response without duplicating state", async ({
  page: _page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  const port = 8020;
  const key = crypto.randomUUID();
  const payload = {
    propertySlug: "phase-19-home",
    formVersion: "property-inquiry-1.0",
    contact: {
      fullName: "Synthetic API Restart",
      email: "api-restart@example.com",
      preferredContactMethod: "email",
    },
    inquiry: { intent: "information" },
    consent: {
      privacyNoticeVersion: "client-value-is-not-authoritative",
      requestedContact: true,
      marketing: false,
      adMeasurement: false,
    },
  };
  const post = async () =>
    fetch(`http://127.0.0.1:${port}/api/v1/leads`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify(payload),
    });
  let api = startApi(port);
  try {
    await waitForApi(port);
    const initial = await post();
    expect(initial.status).toBe(201);
    const accepted = (await initial.json()) as { inquiryId: string; reference: string };
    await stopWorker(api);
    api = startApi(port);
    await waitForApi(port);
    const replay = await post();
    expect(replay.status).toBe(201);
    expect(await replay.json()).toMatchObject(accepted);
    expect(
      queryJson(
        "SELECT count(DISTINCT i.id)::int AS inquiries,count(DISTINCT o.id)::int AS outbox " +
          "FROM contacts c JOIN inquiries i ON i.contact_id=c.id " +
          "JOIN outbox_jobs o ON o.aggregate_id=i.id " +
          "WHERE c.normalized_email='api-restart@example.com'",
      ),
    ).toMatchObject({ inquiries: 1, outbox: 1 });
  } finally {
    await stopWorker(api);
  }
});

test("delivery limits surface a dead job after worker restart without making the API unready", async ({
  page: _page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  const contactId = crypto.randomUUID();
  const inquiryId = crypto.randomUUID();
  const jobId = crypto.randomUUID();
  const reference = "RE-DEADJOB028";
  psql(
    "INSERT INTO contacts (id,full_name,normalized_email) " +
      `VALUES ('${contactId}','Synthetic Dead Job','dead-job@example.com'); ` +
      "INSERT INTO inquiries (id,public_reference,contact_id,property_id,source_platform,form_version) " +
      `VALUES ('${inquiryId}','${reference}','${contactId}','${syntheticPropertyId}','direct','phase-28-dead'); ` +
      "INSERT INTO outbox_jobs " +
      "(id,job_kind,aggregate_id,dedupe_key,payload,state,attempts,available_at,created_at) " +
      `VALUES ('${jobId}','lead_email','${inquiryId}','lead_email:${inquiryId}',` +
      `jsonb_build_object('inquiryId','${inquiryId}','propertyId','${syntheticPropertyId}'),` +
      "'pending',12,now()+interval '1 hour',now())",
  );
  const worker = startWorker();
  await new Promise((resolve) => setTimeout(resolve, 500));
  await stopWorker(worker);
  psql(
    "UPDATE outbox_jobs SET available_at=now() " +
      `WHERE aggregate_id=(SELECT id FROM inquiries WHERE public_reference='${reference}')`,
  );
  const replacement = startWorker();
  try {
    const dead = await waitForOutbox(reference, "dead");
    expect(dead).toMatchObject({
      state: "dead",
      attempts: 12,
      last_error_code: "delivery_limits_exceeded",
    });
    expect((await fetch("http://127.0.0.1:8019/health/ready")).status).toBe(200);
  } finally {
    await stopWorker(replacement);
  }
});
