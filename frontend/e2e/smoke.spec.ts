import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const TENANT = process.env.E2E_TENANT ?? 'demo-oncology';
const USER = process.env.E2E_USER ?? 'analyst@demo.example';
const PASSWORD = process.env.E2E_PASSWORD ?? 'ChangeMe-Demo-2026!';
const SHOTS = process.env.E2E_SCREENSHOT_DIR ?? join(__dirname, 'screenshots');
mkdirSync(SHOTS, { recursive: true });

async function login(page: Page) {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel('Tenant').fill(TENANT);
  await page.getByLabel('Email').fill(USER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Portfolio' })).toBeVisible();
}

test('analyst: dashboard -> executive alert event -> evidence -> ask', async ({ page }) => {
  await login(page);

  // ---- Home / Portfolio
  await expect(page.getByRole('heading', { name: 'Your assets' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'XD-101', exact: true })).toBeVisible();
  const dev = page.getByRole('region', { name: 'Material developments' });
  const alertLink = dev.getByRole('link', { name: /NCT99000001: enrollment 320.480/ });
  await expect(alertLink).toBeVisible();
  await expect(page.getByRole('contentinfo')).toContainText('Decision-support output. Facts are evidence-linked; interpretations are AI-generated hypotheses.');
  await page.screenshot({ path: join(SHOTS, 'dashboard.png'), fullPage: false });

  // ---- Event detail (interaction 1)
  await alertLink.click();
  await expect(page).toHaveURL(/\/events\//);
  await expect(page.getByText('Executive Alert').first()).toBeVisible();

  const diff = page.getByRole('table', { name: /Field changes between source snapshots/ });
  const enrollment = diff.getByRole('row', { name: /Enrollment/ });
  await expect(enrollment).toContainText('320');
  await expect(enrollment).toContainText('480');
  await expect(diff.getByRole('row', { name: /Primary completion date/ })).toContainText('2027-11');
  await expect(diff.getByRole('row', { name: /Primary endpoints/ })).toContainText('Progression-Free Survival');

  const path = page.getByRole('list', { name: /Impact path: XD-101 -> competes_with CA-201 -> evaluated_in NCT99000001/ });
  await expect(path).toBeVisible();
  await expect(path).toContainText('competes_with');
  await expect(path).toContainText('evaluated_in');

  const fact = page.locator('[data-statement-type="FACT"]').first();
  const inference = page.locator('[data-statement-type="INFERENCE"]').first();
  await expect(fact).toContainText('Verified fact');
  await expect(inference).toContainText('AI interpretation');
  await expect(inference).not.toContainText('Verified fact');
  await expect(page.locator('[data-statement-type="UNKNOWN"]').first()).toContainText('Unknown');
  await expect(page.getByText(/facts supported by evidence/)).toBeVisible();
  await page.screenshot({ path: join(SHOTS, 'event.png'), fullPage: false });
  // Explainable AI: plain-language why, drivers, counterfactuals, knowledge limits
  const why = page.getByTestId('explanation-panel');
  await expect(why).toBeVisible();
  await expect(why.getByText(/In plain language/)).toBeVisible();
  await expect(why.getByRole('region', { name: 'Knowledge limits' })).toBeVisible();
  await why.screenshot({ path: join(SHOTS, 'why.png') });

  // ---- Evidence drawer (interaction 2)
  await fact.getByRole('button', { name: /Open evidence S1/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Evidence S1' });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('Enrollment changed from 320 to 480');
  await expect(drawer).toContainText('ClinicalTrials.gov');
  await expect(drawer).toContainText('Retrieved');
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();

  // ---- Ask the landscape (streamed)
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Ask' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Ask the landscape' })).toBeVisible();
  await page.getByLabel('Your question').fill('What changed this week?');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(page.getByRole('list', { name: 'Answer progress' })).toBeVisible();
  const answer = page.getByRole('article', { name: 'Answer' }).last();
  await expect(answer).toBeVisible({ timeout: 45_000 });
  await expect(answer).toContainText(/change record/);
  await expect(answer.locator('[data-statement-type="FACT"]').first()).toContainText('Verified fact');
  await expect(page.getByRole('list', { name: 'Answer progress' }).last()).toContainText('Validating against evidence');
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}/);
  await page.screenshot({ path: join(SHOTS, 'ask.png'), fullPage: false });
});
