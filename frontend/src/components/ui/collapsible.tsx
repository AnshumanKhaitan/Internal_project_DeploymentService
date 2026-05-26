"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { ChevronDown } from "lucide-react"

interface CollapsibleProps {
  children: React.ReactNode
  defaultOpen?: boolean
  className?: string
}

interface CollapsibleContextValue {
  isOpen: boolean
  toggle: () => void
}

const CollapsibleContext = React.createContext<CollapsibleContextValue>({
  isOpen: true,
  toggle: () => {},
})

function Collapsible({ children, defaultOpen = true, className }: CollapsibleProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen)
  const toggle = React.useCallback(() => setIsOpen((prev) => !prev), [])

  return (
    <CollapsibleContext.Provider value={{ isOpen, toggle }}>
      <div data-slot="collapsible" className={cn("", className)} data-state={isOpen ? "open" : "closed"}>
        {children}
      </div>
    </CollapsibleContext.Provider>
  )
}

function CollapsibleTrigger({ children, className, ...props }: React.ComponentProps<"button">) {
  const { isOpen, toggle } = React.useContext(CollapsibleContext)

  return (
    <button
      data-slot="collapsible-trigger"
      type="button"
      onClick={toggle}
      className={cn("flex w-full items-center justify-between cursor-pointer", className)}
      {...props}
    >
      {children}
      <ChevronDown
        className={cn(
          "h-4 w-4 text-muted-foreground transition-transform duration-200",
          isOpen && "rotate-180"
        )}
      />
    </button>
  )
}

function CollapsibleContent({ children, className, ...props }: React.ComponentProps<"div">) {
  const { isOpen } = React.useContext(CollapsibleContext)

  return (
    <div
      data-slot="collapsible-content"
      className={cn(
        "overflow-hidden transition-all duration-300 ease-in-out",
        isOpen ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
