export interface User {
  id: number;
  name: string;
  email: string;
}

export type UserRole = "admin" | "viewer" | "editor";

export interface ApiResponse<T> {
  data: T;
  status: number;
  message: string;
}
