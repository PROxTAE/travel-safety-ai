import { AssistantView } from "@/features/conversations/assistant-view";

export default async function AssistantConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return <AssistantView conversationId={conversationId} />;
}
