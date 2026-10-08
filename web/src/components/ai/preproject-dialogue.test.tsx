import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { PreprojectDialogue, type PreprojectAssessment } from "./preproject-dialogue";

afterEach(cleanup);
const clarify: PreprojectAssessment = {goal:"category",stage:"clarify",candidate_digest:"a".repeat(64),category:null,proposal:null,questions:[{id:"region",question:"先卖哪个地区？",options:["EU","US"],recommendation:"先从EU开始"}]};
const ready: PreprojectAssessment = {...clarify,stage:"ready",questions:[],category:{code:"SUP",title:"桨板充气泵",user_groups:["休闲用户"],regions:["EU"],use_scenarios:["码头"],research_questions:["法规适用性待确认"],parameters:[{key:"runtime",label:"续航",unit:"min",conditions:"负载待专家",direction:"higher"}],notes:[]}};

test("recommendation does not answer automatically; explicit answer returns to the same dialogue", () => {
  const answer=vi.fn();render(<PreprojectDialogue assessment={clarify} disabled={false} onAnswer={answer} onConfirm={vi.fn()}/>);
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.getByRole("radio", {name:"EU"})).not.toBeChecked();
  fireEvent.click(screen.getByRole("radio", {name:"EU"}));
  fireEvent.click(screen.getByRole("button", {name:"回答并继续"}));
  expect(answer).toHaveBeenCalledWith("region：EU");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("adoption shows full candidate and sources, requires human share decision, and retains failed candidate for retry", async () => {
  const confirm=vi.fn().mockRejectedValueOnce(new Error("连接中断，查询或重试原候选")).mockResolvedValueOnce(undefined);
  render(<PreprojectDialogue assessment={ready} disabled={false} citations={[{reference_id:"snapshot:1",label:"公开依据",href:"https://example.com/spec"}]} onAnswer={vi.fn()} onConfirm={confirm}/>);
  expect(screen.getByText(/负载待专家/)).toBeVisible();
  expect(screen.getByRole("link", {name:"公开依据"})).toHaveAttribute("href","https://example.com/spec");
  const save=screen.getByRole("button", {name:"保存品类与资料"});expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));fireEvent.click(save);
  expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
  expect(screen.getByRole("dialog")).toBeVisible();fireEvent.click(save);
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(confirm).toHaveBeenCalledTimes(2);
});

test("restored candidate waits for an explicit click before opening its popup", () => {
  render(<PreprojectDialogue assessment={clarify} autoOpen={false} disabled={false} onAnswer={vi.fn()} onConfirm={vi.fn()}/>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"回答关键问题"}));
  expect(screen.getByRole("dialog")).toBeVisible();
});
