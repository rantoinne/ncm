import { readFile } from "fs";
import type { Config } from "./config";

export interface User {
  id: string;
}

export class Service {
  run(): void {
    helper();
  }
}

export function helper(): string {
  return "ok";
}

export const arrow = (): number => {
  return helper().length;
};

type ID = string;
