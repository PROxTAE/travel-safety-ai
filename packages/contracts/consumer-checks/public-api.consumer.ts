// Compile-time consumer check for the generated TypeScript contract.
//
// This file is never executed and never shipped. It exists so that `npm run typecheck` fails the
// moment a contract change would break the web app: if a field is renamed, made required, or has
// its type narrowed, the assignments below stop compiling. That is cheaper than finding out from a
// runtime error in the browser.
//
// Keep the assertions here to the shapes the UI actually depends on. It is a smoke test for the
// contract, not a second copy of it.

import type { components, operations, paths } from '../generated/typescript/public-api.js';

type Schemas = components['schemas'];

// --- The endpoints the web app calls must exist with the verbs it uses. -----------------------

type _AssessmentsIsPost = paths['/api/v1/trips/{trip_id}/assessments']['post'];
type _RunEventsIsGet = paths['/api/v1/runs/{request_id}/events']['get'];
type _ApplyRouteIsPost = paths['/api/v1/trips/{trip_id}/apply-route']['post'];

// --- Starting an assessment answers with a run reference the client can follow. ---------------

type CreateAssessment = operations['createAssessment'];
type AcceptedBody = CreateAssessment['responses']['202']['content']['application/json'];

const accepted: AcceptedBody = {
  data: {
    request_id: 'b2c3d4e5-f6a7-4b89-9c0d-1e2f3a4b5c6d',
    status: 'QUEUED',
    events_url: '/api/v1/runs/b2c3d4e5-f6a7-4b89-9c0d-1e2f3a4b5c6d/events',
    poll_url: '/api/v1/runs/b2c3d4e5-f6a7-4b89-9c0d-1e2f3a4b5c6d',
    submitted_at: '2026-09-19T08:15:00Z',
  },
  meta: {
    request_id: 'b2c3d4e5-f6a7-4b89-9c0d-1e2f3a4b5c6d',
    contract_version: '1.0.0',
    generated_at: '2026-09-19T08:15:00Z',
  },
};
void accepted;

// --- The four actions are closed. A fifth would break every switch in the UI. ------------------

const everyAction: Schemas['ActionCode'][] = ['NORMAL', 'CHANGE_ROUTE', 'DELAY', 'AVOID'];
void everyAction;

// @ts-expect-error a value outside the ActionCode vocabulary must not type-check
const invalidAction: Schemas['ActionCode'] = 'PROCEED_WITH_CAUTION';
void invalidAction;

// --- Safety-bearing fields the UI is required to render must stay non-optional. ----------------

function renderRecommendation(recommendation: Schemas['RecommendationResponse']): string {
  // Freshness and sources are what let the UI show where an answer came from and how old it is.
  const fetchedAt: string = recommendation.freshness.fetched_at;
  const sourceCount: number = recommendation.sources.length;
  const degraded: number = recommendation.degraded_services.length;
  const limitations: number = recommendation.limitations.length;
  return `${recommendation.action_code} ${fetchedAt} ${sourceCount} ${degraded} ${limitations}`;
}
void renderRecommendation;

// A route that an official source has closed must always expose that fact.
function isRouteClosed(route: Schemas['RouteCandidate']): boolean {
  return route.exposure.closed;
}
void isRouteClosed;

// --- Progress events carry an i18n key, never a pre-translated sentence. -----------------------

function progressKey(event: Schemas['SseRunProgress']): string {
  const percent: number | null = event.percent ?? null;
  void percent;
  return event.message_key;
}
void progressKey;

// --- Errors are a closed, stable set the UI can branch on. ------------------------------------

function isRetryable(error: Schemas['ErrorResponse']['error']): boolean {
  switch (error.code) {
    case 'RATE_LIMITED':
    case 'DEPENDENCY_TIMEOUT':
    case 'DEPENDENCY_UNAVAILABLE':
      return true;
    default:
      return error.retryable;
  }
}
void isRetryable;
