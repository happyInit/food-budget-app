import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

import { recordRumRouteChange } from '../../lib/rum'

// This component observes routing only. It neither changes navigation nor
// waits for telemetry delivery, so a receiver failure cannot affect the UI.
export default function RumRouteTracker() {
  const location = useLocation()

  useEffect(() => {
    recordRumRouteChange(location.pathname)
  }, [location.pathname])

  return null
}
