/**
 * Project API module for ChipCompiler
 */

import { alovaInstance } from './client'

// Types for API requests and responses
export interface ProjectInfo {
  name: string
  path: string
  flow?: Record<string, unknown>
}

export interface ProjectResponse {
  status: 'success' | 'error'
  message?: string
  project?: ProjectInfo
}

export interface OpenProjectRequest {
  path: string
}

export interface CreateProjectRequest {
  path: string
  name?: string
}

/**
 * Open an existing project
 * @param path - Full path to the project directory
 */
export function openProjectApi(path: string) {
  return alovaInstance.Post<ProjectResponse>('/api/project/open', {
    path
  } as OpenProjectRequest)
}

/**
 * Create a new project
 * @param path - Parent directory where the project will be created
 * @param name - Name of the new project (optional, defaults to "New_Chip_Design")
 */
export function createProjectApi(path: string, name?: string) {
  return alovaInstance.Post<ProjectResponse>('/api/project/create', {
    path,
    name: name || 'New_Chip_Design'
  } as CreateProjectRequest)
}

/**
 * Check project API health
 */
export function checkProjectApiHealth() {
  return alovaInstance.Get<{ status: string }>('/api/project/health')
}
