import { User, ApiResponse } from "./types";

export function getUser(id: number): ApiResponse<User> {
  const user: User = { id, name: "Alice", email: "alice@example.com" };
  return { data: user, status: 200, message: "OK" };
}

export function createUser(name: string, email: string): User {
  return { id: Math.random(), name, email };
}

function internalHelper(x: number): number {
  return x * 2;
}
