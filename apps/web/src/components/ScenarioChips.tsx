"use client";

interface ScenarioChipsProps {
  onSelect: (goal: string) => void;
  disabled?: boolean;
}

const SCENARIOS = [
  {
    category: "🏝️ Travel & Lifestyle",
    chips: [
      {
        label: "Dream Island Trip",
        goal: "I want to go to the best island in the world. Recommend where I should go and prepare a travel brief with pictures.",
        icon: "🏝️",
      },
      {
        label: "Island + Audio Guide",
        goal: "Recommend the best island in the world with pictures AND an audio narration of the top picks.",
        icon: "🎧",
      },
    ],
  },
  {
    category: "💼 Business & Work",
    chips: [
      {
        label: "Business Launch Package",
        goal: "I'm starting my new business project tomorrow. Prepare everything I need: business plan doc, learning materials, budget sheet, pitch deck, kickoff meeting, and tasks.",
        icon: "🚀",
      },
      {
        label: "Email Summary",
        goal: "Search my inbox for recent emails and create a summary of what I missed.",
        icon: "📧",
      },
      {
        label: "Career Growth Plan",
        goal: "Help me get promoted to senior engineer in 6 months. Create a skill development roadmap.",
        icon: "📈",
      },
    ],
  },
  {
    category: "🎓 Learning & Development",
    chips: [
      {
        label: "Learn AI Roadmap",
        goal: "Prepare a comprehensive plan to learn AI in 2026, including resources and a study schedule.",
        icon: "🤖",
      },
      {
        label: "Audio AI Briefing",
        goal: "Give me an audio briefing about the most important AI news this week.",
        icon: "🎙️",
      },
    ],
  },
  {
    category: "💰 Personal Finance",
    chips: [
      {
        label: "House Down Payment",
        goal: "Create a budget plan to save for a house down payment. I earn $80k/year.",
        icon: "🏠",
      },
      {
        label: "Wealth Strategy",
        goal: "How do I get rich? Give me an honest, research-based wealth building strategy.",
        icon: "💰",
      },
    ],
  },
  {
    category: "🎮 Creative & Demo",
    chips: [
      {
        label: "Ghost Run Game Concept",
        goal: "Evaluate whether Ghost Run can succeed commercially and prepare everything I need for launch.",
        icon: "👻",
      },
      {
        label: "Creative Short Story",
        goal: "Write a short story about time travel with character development and plot twists.",
        icon: "📚",
      },
    ],
  },
];

export default function ScenarioChips({ onSelect, disabled }: ScenarioChipsProps) {
  return (
    <div className="space-y-4">
      {SCENARIOS.map((category) => (
        <div key={category.category}>
          <h3 className="text-sm font-semibold text-zinc-400 mb-2">{category.category}</h3>
          <div className="flex flex-wrap gap-2">
            {category.chips.map((chip) => (
              <button
                key={chip.label}
                onClick={() => onSelect(chip.goal)}
                disabled={disabled}
                className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 
                         text-zinc-200 text-sm transition-colors disabled:opacity-50 
                         disabled:cursor-not-allowed border border-zinc-700"
              >
                <span className="mr-1">{chip.icon}</span>
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}