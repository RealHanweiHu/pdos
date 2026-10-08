import { Agent, type Dispatcher } from "undici";

// Keep fetch's independent header/body timers within the candidate's total budget.
// This dispatcher is opt-in per request; other operations keep Node's defaults.
const candidateDispatcher: Dispatcher = new Agent({
  headersTimeout: 600000,
  bodyTimeout: 600000,
});

export function candidateTransportOptions(candidate: boolean): {
  dispatcher?: Dispatcher;
} {
  return candidate ? { dispatcher: candidateDispatcher } : {};
}
