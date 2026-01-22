export enum CMDEnum {
  create_workspace = "create_workspace",
  load_workspace = "load_workspace",
  delete_workspace = "delete_workspace"
}

export enum ResponseEnum {
  success = "success",
  failed = "failed",
  error = "error"
}

export interface RequestData<T> {
  cmd: CMDEnum;
  data: T;
}

export interface ResponseData<T> {
  cmd: CMDEnum;
  response: ResponseEnum;
  data: T;
  message: string[];
}