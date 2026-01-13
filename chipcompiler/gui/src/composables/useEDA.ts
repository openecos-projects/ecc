import { invoke } from '@tauri-apps/api/core'
import { convertFileSrc } from '@tauri-apps/api/core'
import { readFile } from '@tauri-apps/plugin-fs'

export interface PyResult {
  code: number
  stdout: string
  stderr: string
}

export interface EdaResponse<T = any> {
  status: 'success' | 'error'
  payload?: T
  message?: string
  traceback?: string
}

export function useEDA() {
  /**
   * 调用 Python EDA 后端的通用函数
   * @param scriptPath 脚本相对于 python/ 目录的路径，或者绝对路径
   * @param funcName 函数名
   * @param args 函数参数
   */
  const callEdaFunc = async <T = any>(
    scriptPath: string,
    funcName: string,
    args: any = {}
  ): Promise<EdaResponse<T>> => {
    try {
      const res = (await invoke('call_python_func', {
        scriptPath,
        funcName,
        args
      })) as PyResult
      console.log('从 python 后端获取的数据', res);
      // 优先从 stdout 解析 JSON 错误信息
      if (res.stdout) {
        try {
          const response = JSON.parse(res.stdout) as EdaResponse<T>
          if (res.code !== 0 || response.status === 'error') {
            return {
              status: 'error',
              message: response.message || res.stderr || 'Python execution failed',
              traceback: response.traceback
            }
          }
          return response
        } catch (e) {
          // 忽略解析失败，继续后面的逻辑
        }
      }

      if (res.code !== 0) {
        return {
          status: 'error',
          message: res.stderr || 'Python execution failed'
        }
      }

      return JSON.parse(res.stdout)
    } catch (error) {
      console.error('EDA Call Error:', error)
      return {
        status: 'error',
        message: String(error)
      }
    }
  }

  /**
   * 将本地资源路径转换为可在 PIXI 中使用的 URL
   * 使用 fs plugin 读取文件并创建 blob URL，绕过 asset protocol 限制
   */
  const getResourceUrl = async (path: string, projectPath: string): Promise<string> => {
    try {
      // 构建完整路径
      let fullPath = path
      if (!path.startsWith('/') && !/^[a-zA-Z]:/.test(path)) {
        const separator = projectPath.endsWith('/') || projectPath.endsWith('\\') ? '' : '/'
        fullPath = `${projectPath}${separator}${path}`
      }

      console.log('Reading file from:', fullPath)

      // 使用 fs plugin 读取文件
      const fileData = await readFile(fullPath)

      // 创建 Blob
      const blob = new Blob([fileData], { type: 'image/png' })

      // 创建 blob URL
      const blobUrl = URL.createObjectURL(blob)

      console.log('Created blob URL:', blobUrl)
      return blobUrl
    } catch (error) {
      console.error('Failed to create blob URL:', error)
      // 如果读取失败，回退到 convertFileSrc
      if (path.startsWith('/') || /^[a-zA-Z]:/.test(path)) {
        return convertFileSrc(path)
      }
      const separator = projectPath.endsWith('/') || projectPath.endsWith('\\') ? '' : '/'
      const fullPath = `${projectPath}${separator}${path}`
      return convertFileSrc(fullPath)
    }
  }

  return {
    callEdaFunc,
    getResourceUrl
  }
}
