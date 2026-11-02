"use client";
import { createContext, useContext, useEffect, useRef } from "react";
import type { ProfessionalTarget } from "@/lib/professional-records";

export const ProfessionalTargetContext = createContext<{target:ProfessionalTarget; serial:number}|null>(null);
/** Select only an option returned by the current authorized reader. Never submits. */
export function useProfessionalSelection(key:keyof ProfessionalTarget, options:readonly string[], selected:string, blocked:boolean, choose:(id:string)=>void) {
  const intent=useContext(ProfessionalTargetContext), consumed=useRef("");
  const target=intent?.target[key]??"", serial=intent?.serial??0;
  const callback=useRef(choose);
  useEffect(()=>{callback.current=choose;},[choose]);
  useEffect(()=>{
    const token=`${serial}:${key}:${target}`;
    if(!target||blocked||consumed.current===token||!options.includes(target))return;
    consumed.current=token;
    if(selected!==target)callback.current(target);
  },[target,serial,key,options,selected,blocked]);
}
