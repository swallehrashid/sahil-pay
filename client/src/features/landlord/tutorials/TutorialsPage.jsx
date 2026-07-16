import { Sparkles } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import SahilPayLogo from "@/components/branding/SahilPayLogo";
import { useOnboardingState } from "./useOnboardingState";
import { useTour } from "./TourProvider";
import { TUTORIALS, SECTIONS } from "./content";

function TutorialCard({ tutorial, status, onStart }) {
  const Icon = tutorial.icon;
  return (
    <div className="glass card-hover flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-secondary/20 text-secondary-100">
          {Icon && <Icon className="h-5 w-5" />}
        </span>
        {status === "completed" && <Badge color="emerald">Completed</Badge>}
        {status === "skipped" && <Badge color="white">Skipped</Badge>}
        {!status && <Badge color="white">Not started</Badge>}
      </div>
      <div>
        <h3 className="text-sm font-medium text-white">{tutorial.title}</h3>
        <p className="mt-1 text-xs text-white/40">{tutorial.duration}</p>
      </div>
      <Button variant="subtle" size="sm" className="mt-auto self-start" onClick={onStart}>
        {status ? "Run again" : "Start"}
      </Button>
    </div>
  );
}

export default function TutorialsPage() {
  const { tutorialStatus } = useOnboardingState();
  const { startTutorial, startSequence } = useTour();

  return (
    <div>
      <SahilPayLogo withSlogan={false} className="mb-4 h-8 text-white/90" />
      <PageHeader
        title="Help & Tutorials"
        subtitle="Step-by-step guides to everything in Sahil Pay. Run any of them as many times as you like."
      />

      <div className="glass mb-8 flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-secondary/20 text-secondary-100">
            <Sparkles className="h-5 w-5" />
          </span>
          <div>
            <p className="text-sm font-medium text-white">New here? Start with the guided setup.</p>
            <p className="text-xs text-white/40">Property → units → tenant → invoice → payment → messaging, in one flow.</p>
          </div>
        </div>
        <Button onClick={startSequence}>Run the full guided setup</Button>
      </div>

      <div className="space-y-8">
        {SECTIONS.map((section) => {
          const items = TUTORIALS.filter((t) => t.section === section.key);
          if (!items.length) return null;
          return (
            <div key={section.key}>
              <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-white/40">{section.label}</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((tutorial) => (
                  <TutorialCard
                    key={tutorial.id}
                    tutorial={tutorial}
                    status={tutorialStatus(tutorial.id)}
                    onStart={() => startTutorial(tutorial.id, { origin: "standalone" })}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
