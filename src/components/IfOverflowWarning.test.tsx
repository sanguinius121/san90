// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { IfOverflowWarning } from "./IfOverflowWarning";
import { useDeviceStore, useDisplayStore, useRuntimeStore } from "../stores";

afterEach(() => {
  cleanup();
  useRuntimeStore.setState({ ifOverflow: false });
});

describe("IfOverflowWarning", () => {
  it("renders the warning while overflow is active", () => {
    useRuntimeStore.setState({ ifOverflow: true });
    render(<IfOverflowWarning />);
    expect(screen.getByRole("alert").textContent).toBe("IF OVERFLOW");
  });

  it("is hidden when overflow is inactive", () => {
    render(<IfOverflowWarning />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("remains active while a verified Reference Level updates the Y-axis", () => {
    useRuntimeStore.setState({ ifOverflow: true });
    render(<IfOverflowWarning />);

    useDeviceStore.setState({ referenceDbm: 0 });
    useDisplayStore.getState().setSpectrumReferenceLevel(0);

    expect(useDisplayStore.getState().viewport.maxDbm).toBe(0);
    expect(useRuntimeStore.getState().ifOverflow).toBe(true);
    expect(screen.getByRole("alert").textContent).toBe("IF OVERFLOW");
  });
});
