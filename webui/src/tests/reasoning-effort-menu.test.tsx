import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReasoningEffortMenu } from "@/components/thread/ReasoningEffortMenu";
import { setAppLanguage } from "@/i18n";

function renderMenu(value: string | null, disabled = false) {
  const onChange = vi.fn();
  const view = render(
    <ReasoningEffortMenu value={value} onChange={onChange} disabled={disabled} />,
  );
  return { onChange, ...view };
}

describe("ReasoningEffortMenu", () => {
  beforeEach(async () => {
    // The pill reuses the shared reasoning-effort labels, which localize
    // Simplified Chinese; pin the language so the assertions are stable.
    await act(async () => {
      await setAppLanguage("zh-CN");
    });
  });

  it("renders the pill with the formatted effort and its label", () => {
    renderMenu("high");

    const trigger = screen.getByRole("button", { name: "思考强度: 高" });
    expect(trigger).toHaveTextContent("高");
    expect(trigger).toHaveAttribute("title", "本会话的思考强度");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("falls back to the default label when no effort is set", () => {
    renderMenu(null);

    expect(screen.getByRole("button", { name: "思考强度: 默认" })).toHaveTextContent("默认");
  });

  it("opens the menu with every offered level", async () => {
    const user = userEvent.setup();
    renderMenu("high");

    await user.click(screen.getByRole("button", { name: "思考强度: 高" }));

    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "默认",
      "关闭",
      "低",
      "中",
      "高",
      "极高",
    ]);
    expect(screen.getByRole("option", { name: "高" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "思考强度: 高" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("selecting 高 calls onChange with the provider token", async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu("low");

    await user.click(screen.getByRole("button", { name: "思考强度: 低" }));
    await user.click(await screen.findByRole("option", { name: "高" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("high");
    await waitFor(() => {
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });
  });

  it("selecting 默认 sends the default token", async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu("xhigh");

    await user.click(screen.getByRole("button", { name: "思考强度: 极高" }));
    await user.click(await screen.findByRole("option", { name: "默认" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("default");
  });

  it("keeps the menu closed while disabled", async () => {
    const user = userEvent.setup();
    const { onChange } = renderMenu("high", true);

    const trigger = screen.getByRole("button", { name: "思考强度: 高" });
    expect(trigger).toBeDisabled();
    await user.click(trigger);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
