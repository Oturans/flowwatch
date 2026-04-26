"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "@/components/ui/use-toast";

export function useEventStream() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const eventSource = new EventSource(`${apiUrl}/api/events/stream`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Invalidate relevant queries to trigger refetch
        queryClient.invalidateQueries({ queryKey: ["events"] });
        queryClient.invalidateQueries({ queryKey: ["dashboard"] });
        
        // Show notification for new events
        if (data.status === "error" || data.status === "failed") {
          toast({
            title: "Workflow Failed",
            description: `${data.workflow_id} failed`,
            variant: "destructive",
          });
        }
      } catch (e) {
        // Ignore parse errors for non-JSON messages
      }
    };

    eventSource.onerror = () => {
      // EventSource auto-reconnects, but we can log if needed
    };

    return () => {
      eventSource.close();
    };
  }, [queryClient]);
}