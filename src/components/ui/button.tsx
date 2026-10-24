import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
const variants=cva('button',{variants:{variant:{default:'primary',outline:'outline',ghost:'ghost',danger:'danger'}},defaultVariants:{variant:'default'}});
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>,VariantProps<typeof variants>{}
export const Button=forwardRef<HTMLButtonElement,ButtonProps>(({className,variant,...props},ref)=><button ref={ref} className={twMerge(clsx(variants({variant}),className))} {...props}/>);
Button.displayName='Button';
