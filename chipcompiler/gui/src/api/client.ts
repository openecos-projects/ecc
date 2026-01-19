/**
 * Alova HTTP client configuration for ChipCompiler API
 */

import { createAlova } from 'alova'
import adapterFetch from 'alova/fetch'

// API server configuration
const API_HOST = '127.0.0.1'
const API_PORT = 8765
const API_BASE_URL = `http://${API_HOST}:${API_PORT}`

/**
 * Alova instance configured for ChipCompiler backend API
 */
export const alovaInstance = createAlova({
  baseURL: API_BASE_URL,
  requestAdapter: adapterFetch(),
  
  // Request interceptor
  beforeRequest(method) {
    // Add common headers
    method.config.headers = {
      ...method.config.headers,
      'Content-Type': 'application/json',
    }
  },
  
  // Response interceptor
  responded: {
    // Handle successful response
    async onSuccess(response) {
      const json = await response.json()
      return json
    },
    
    // Handle error response
    onError(error) {
      console.error('API request failed:', error)
      throw error
    }
  }
})

/**
 * Check if the API server is available
 */
export async function checkApiHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    })
    return response.ok
  } catch {
    return false
  }
}

export { API_BASE_URL, API_HOST, API_PORT }
