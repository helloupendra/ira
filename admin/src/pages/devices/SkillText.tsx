// "Files: find files by name, ..." reads as a bold name over what it reads.
export function SkillText({ description }: { description: string }) {
  const at = description.indexOf(': ');
  if (at <= 0 || at > 24) return <span className="skill-desc">{description}</span>;
  return (
    <span className="skill-text">
      <span className="skill-name">{description.slice(0, at)}</span>
      <span className="skill-desc">{description.charAt(at + 2).toUpperCase() + description.slice(at + 3)}</span>
    </span>
  );
}
