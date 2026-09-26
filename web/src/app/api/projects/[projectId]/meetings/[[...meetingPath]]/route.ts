import { forwardMeetings } from "@/lib/meetings-bff";

type Context = {
  params: Promise<{ projectId: string; meetingPath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardMeetings("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardMeetings("POST", request, context);
}

export function PUT(request: Request, context: Context) {
  return forwardMeetings("PUT", request, context);
}
