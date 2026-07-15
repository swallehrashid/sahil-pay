import { useNavigate } from "react-router-dom";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";

// Slide-carousel renderer for conceptual tutorials — pure content, no DOM anchors, so it
// can never break from UI drift (ONBOARDING_TUTORIALS_SPEC.md §5.3).
export default function ExplainerModal({ tutorial, slideIndex, onNext, onBack, onDone, onSkip, doneLabel = "Done" }) {
  const navigate = useNavigate();
  const slide = tutorial.slides[slideIndex];
  const isLast = slideIndex === tutorial.slides.length - 1;
  const Icon = slide.icon;

  const handleCta = () => {
    onDone();
    if (tutorial.cta?.route) navigate(tutorial.cta.route);
  };

  return (
    <Modal isOpen onClose={onSkip} title={tutorial.title} size="sm">
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          {Icon && (
            <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-secondary/20 text-secondary-100">
              <Icon className="h-5 w-5" />
            </span>
          )}
          <div>
            <h3 className="text-base font-medium text-white">{slide.title}</h3>
            {slide.body && <p className="mt-1 whitespace-pre-line text-sm text-white/70">{slide.body}</p>}
            {slide.bullets && (
              <ul className="mt-2 space-y-1.5">
                {slide.bullets.map((b) => (
                  <li key={b} className="flex gap-2 text-sm text-white/70">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-secondary" />
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="flex items-center justify-center gap-1.5 pt-1">
          {tutorial.slides.map((s, i) => (
            <span
              key={s.title}
              className={
                "h-1.5 rounded-full transition-all duration-200 " +
                (i === slideIndex ? "w-4 bg-secondary" : "w-1.5 bg-white/20")
              }
            />
          ))}
        </div>

        <div className="flex items-center justify-between gap-3 pt-2">
          <Button variant="ghost" size="sm" onClick={onSkip}>
            Skip
          </Button>
          <div className="flex gap-2">
            {slideIndex > 0 && (
              <Button variant="ghost" size="sm" onClick={onBack}>
                Back
              </Button>
            )}
            {isLast && tutorial.cta && (
              <Button variant="subtle" size="sm" onClick={handleCta}>
                {tutorial.cta.label}
              </Button>
            )}
            <Button size="sm" onClick={isLast ? onDone : onNext}>
              {isLast ? doneLabel : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
