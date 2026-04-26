import * as React from "react";
import { type ToastActionElement, type ToastProps } from "@/components/ui/use-toast";

const Toast = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & ToastProps
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      className={className}
      {...props}
    />
  );
});
Toast.displayName = "Toast";

const ToastTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => {
  return (
    <p
      ref={ref}
      className={className}
      {...props}
    />
  );
});
ToastTitle.displayName = "ToastTitle";

const ToastDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => {
  return (
    <p
      ref={ref}
      className={className}
      {...props}
    />
  );
});
ToastDescription.displayName = "ToastDescription";

const ToastClose = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, ...props }, ref) => {
  return (
    <button
      ref={ref}
      className={className}
      {...props}
    />
  );
});
ToastClose.displayName = "ToastClose";

const ToastAction = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & ToastActionElement
>(({ className, ...props }, ref) => {
  return (
    <button
      ref={ref}
      className={className}
      {...props}
    />
  );
});
ToastAction.displayName = "ToastAction";

const ToastViewport = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      className={className}
      {...props}
    />
  );
});
ToastViewport.displayName = "ToastViewport";

export {
  type ToastProps,
  type ToastActionElement,
  Toast,
  ToastTitle,
  ToastDescription,
  ToastClose,
  ToastAction,
  ToastViewport,
};