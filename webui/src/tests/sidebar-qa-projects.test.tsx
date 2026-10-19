
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarQaProjects } from "@/components/SidebarQaProjects";

const projects = [
  { id: "proj_1", key: "SHOP", name: "Demo 商城", repo_path: "/srv/shop" },
  { id: "proj_2", key: "CRM", name: "CRM" },
];

describe("SidebarQaProjects", () => {
  it("lists QA projects and opens a chat for the clicked one", () => {
    const onOpen = vi.fn();
    render(<SidebarQaProjects projects={projects} onOpen={onOpen} />);

    expect(screen.getByText("SHOP")).toBeInTheDocument();
    expect(screen.getByText("CRM")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sidebar-qa-project-proj_1"));
    expect(onOpen).toHaveBeenCalledWith("proj_1");
  });

  it("renders nothing without projects", () => {
    render(<SidebarQaProjects projects={[]} onOpen={() => {}} />);
    expect(screen.queryByTestId("sidebar-qa-projects")).not.toBeInTheDocument();
  });
});
