import { createContext, useContext } from "react";

import type { DispatchTask } from "@/lib/dispatch-desk";

export interface DispatchDeskApi {
  tasks: DispatchTask[];
  focusedTaskId: string | null;
  allTasksOpen: boolean;
  setAllTasksOpen: (open: boolean) => void;
  startDispatch: (prompt: string) => string;
  finishDispatch: (id: string, sessionKey: string | null) => void;
  selectTask: (id: string) => void;
  selectDispatcher: () => void;
  clearFocus: () => void;
}

export const DispatchDeskContext = createContext<DispatchDeskApi | null>(null);

export function useDispatchDesk(): DispatchDeskApi | null {
  return useContext(DispatchDeskContext);
}
