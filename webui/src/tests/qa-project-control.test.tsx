
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QaProjectControl } from "@/components/thread/QaProjectControl";

const project = { id: "proj_1", key: "SHOP", name: "商城" };

describe("QaProjectControl", () => {
  it("shows the bound project and clears the binding", () => {
    const onChange = vi.fn();
    render(
      <QaProjectControl
        project={project}
        projects={[project]}
        onLoadProjects={async () => [project]}
        onChange={onChange}
      />,
    );
    const select = screen.getByTestId("qa-project-control") as HTMLSelectElement;
    expect(select.value).toBe("proj_1");
    fireEvent.change(select, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("loads projects when the control is first used", async () => {
    const onLoadProjects = vi.fn(async () => [project]);
    render(
      <QaProjectControl
        project={null}
        projects={null}
        onLoadProjects={onLoadProjects}
        onChange={() => {}}
      />,
    );
    fireEvent.focus(screen.getByTestId("qa-project-control"));
    await waitFor(() => expect(onLoadProjects).toHaveBeenCalled());
  });

  it("selects a project by id", () => {
    const onChange = vi.fn();
    render(
      <QaProjectControl
        project={null}
        projects={[project]}
        onLoadProjects={async () => [project]}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByTestId("qa-project-control"), {
      target: { value: "proj_1" },
    });
    expect(onChange).toHaveBeenCalledWith("proj_1");
  });
});
