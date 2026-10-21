import React from "react";

/**
 * Clean modern Card component.
 */
export function Card({
  children,
  className = "",
  padding = "md",
  hover = false,
  onClick,
  ...props
}) {
  return (
    <div
      onClick={onClick}
      className={`card card-padding-${padding} ${
        hover ? "card-hover" : ""
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "", ...props }) {
  return (
    <div className={`card-header ${className}`} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = "", as = "h3", ...props }) {
  const Tag = as;
  return (
    <Tag className={`card-title ${className}`} {...props}>
      {children}
    </Tag>
  );
}

export function CardDescription({ children, className = "", ...props }) {
  return (
    <p className={`card-description ${className}`} {...props}>
      {children}
    </p>
  );
}

export function CardContent({ children, className = "", ...props }) {
  return (
    <div className={`card-content ${className}`} {...props}>
      {children}
    </div>
  );
}

export function CardFooter({ children, className = "", ...props }) {
  return (
    <div className={`card-footer ${className}`} {...props}>
      {children}
    </div>
  );
}

export default Card;

