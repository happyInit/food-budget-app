import {
  ErrorsInstrumentation,
  NavigationInstrumentation,
  PerformanceInstrumentation,
  WebVitalsInstrumentation,
  initializeFaro,
  type Faro,
} from '@grafana/faro-web-sdk'

let rum: Faro | undefined

// Dynamic URL values are neither useful RUM dimensions nor safe labels.
// Keep only the route template that the dashboard needs.
export function normalizeRumPath(pathname: string): string {
  if (/^\/recipes\/shared\/[^/]+$/.test(pathname)) return '/recipes/shared/:token'
  if (/^\/recipes\/[^/]+$/.test(pathname)) return '/recipes/:id'
  if (/^\/recipebook\/[^/]+$/.test(pathname)) return '/recipebook/:id'
  if (/^\/shared\/[^/]+$/.test(pathname)) return '/shared/:token'
  if (/^\/auth\/[^/]+\/callback$/.test(pathname)) return '/auth/:provider/callback'
  return pathname
}

export function initializeRum(): void {
  // RUM must never be a prerequisite for the application. With the flag unset,
  // the SDK is not initialized and the existing frontend behaves unchanged.
  if (import.meta.env.VITE_RUM_ENABLED !== 'true' || rum) return

  rum = initializeFaro({
    url: import.meta.env.VITE_RUM_COLLECTOR_URL || '/rum/collect',
    app: {
      name: 'mealplanning-frontend',
      environment: import.meta.env.MODE,
    },
    // Do not collect console output or user-action payloads. RUM needs web
    // vitals, browser errors, and resource timings only.
    instrumentations: [
      new ErrorsInstrumentation(),
      new WebVitalsInstrumentation(),
      new PerformanceInstrumentation(),
      new NavigationInstrumentation(),
    ],
    ignoreUrls: ['/rum/collect'],
    pageTracking: {
      generatePageId: (location) => normalizeRumPath(location.pathname),
    },
    trackGeolocation: false,
    sessionTracking: {
      persistent: false,
    },
  })
}

export function recordRumRouteChange(pathname: string): void {
  rum?.api.pushEvent('route.change', { route: normalizeRumPath(pathname) })
}
