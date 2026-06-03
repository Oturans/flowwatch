"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getSources, createSource, deleteSource, type WebhookSource } from "@/lib/api";
import { Plus, Trash2, Activity } from "lucide-react";

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const { data: sources = [], isLoading } = useQuery({
    queryKey: ["sources"],
    queryFn: getSources,
  });

  const createMutation = useMutation({
    mutationFn: createSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Webhook Sources</h1>
          <p className="text-gray-600 mt-2">Manage your n8n and Make webhook integrations</p>
        </div>
        <AddSourceForm onSubmit={(data) => createMutation.mutate(data)} isLoading={createMutation.isPending} />
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading sources...</div>
      ) : sources.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <Activity className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No sources connected</h3>
          <p className="text-gray-500 mb-4">Add your first webhook source to start monitoring</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              onDelete={() => deleteMutation.mutate(source.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AddSourceForm({
  onSubmit,
  isLoading,
}: {
  onSubmit: (data: { id: string; name: string; signing_secret: string; platform: string }) => void;
  isLoading: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [formData, setFormData] = useState({
    id: "",
    name: "",
    signing_secret: "",
    platform: "n8n",
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
    setFormData({ id: "", name: "", signing_secret: "", platform: "n8n" });
    setIsOpen(false);
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
      >
        <Plus className="w-4 h-4" />
        Add Source
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white p-4 rounded-xl border border-gray-200 flex gap-4">
      <input
        type="text"
        placeholder="Source ID"
        value={formData.id}
        onChange={(e) => setFormData({ ...formData, id: e.target.value })}
        className="px-3 py-2 border border-gray-300 rounded-lg"
        required
      />
      <input
        type="text"
        placeholder="Name"
        value={formData.name}
        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
        className="px-3 py-2 border border-gray-300 rounded-lg"
        required
      />
      <input
        type="text"
        placeholder="Signing Secret"
        value={formData.signing_secret}
        onChange={(e) => setFormData({ ...formData, signing_secret: e.target.value })}
        className="px-3 py-2 border border-gray-300 rounded-lg"
        required
      />
      <select
        value={formData.platform}
        onChange={(e) => setFormData({ ...formData, platform: e.target.value })}
        className="px-3 py-2 border border-gray-300 rounded-lg"
      >
        <option value="n8n">n8n</option>
        <option value="make">Make</option>
        <option value="custom">Custom</option>
      </select>
      <button type="submit" disabled={isLoading} className="px-4 py-2 bg-blue-600 text-white rounded-lg">
        {isLoading ? "Adding..." : "Add"}
      </button>
      <button type="button" onClick={() => setIsOpen(false)} className="px-4 py-2 bg-gray-200 rounded-lg">
        Cancel
      </button>
    </form>
  );
}

function SourceCard({
  source,
  onDelete,
}: {
  source: WebhookSource;
  onDelete: () => void;
}) {
  return (
    <div className="bg-white p-6 rounded-xl border border-gray-200 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="p-3 bg-blue-100 rounded-xl">
          <Activity className="w-6 h-6 text-blue-600" />
        </div>
        <div>
          <h3 className="font-semibold text-gray-900">{source.name}</h3>
          <p className="text-sm text-gray-500">ID: {source.id} • {source.platform}</p>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span
          className={`px-3 py-1 rounded-full text-sm font-medium ${
            source.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
          }`}
        >
          {source.is_active ? "Active" : "Inactive"}
        </span>
        <button
          onClick={onDelete}
          className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
